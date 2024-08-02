import os
import time
import cv2
import logging
from opcua import Client, ua
from threading import Timer

# Define a custom logging level
IMPORTANT = 25
logging.addLevelName(IMPORTANT, "IMPORTANT")

def important(self, message, *args, **kws):
    if self.isEnabledFor(IMPORTANT):
        self._log(IMPORTANT, message, args, **kws)

# Add the custom level to the Logger class
logging.Logger.important = important

# Set up logging to use the custom level
logging.basicConfig(level=IMPORTANT, format='%(asctime)s - %(levelname)s - %(message)s')

OPC_SERVER_URL = os.getenv('OPC_SERVER_URL', 'opc.tcp://10.15.160.149:49312')
TAG_NAME = os.getenv('TAG_NAME', 'ns=2;s=SODA_TEMPLATE.FILTRACAO.RASP_PASSO')
CAMERA_INDEX = int(os.getenv('CAMERA_INDEX', 0))
EQUIPMENT = os.getenv('EQUIPMENT', 'DECANTADOR')
VALID_STEPS = os.getenv('VALID_STEPS', "1;0;1")

NUMBER_OF_PICTURES = int(os.getenv('NUMBER_OF_PICTURES', 1))

if (NUMBER_OF_PICTURES > 100):
    NUMBER_OF_PICTURES = 100

# Base directory to save images
BASE_IMAGE_SAVE_PATH = './data'

def ensure_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)

global cap
cap = None
global step
step = None

def initialize_camera(camera_index=0):
    global cap
    cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)

    # Set resolution to 1920x1080 or the maximum supported by your camera
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    if not cap.isOpened():
        logging.error(f"Failed to open video device {camera_index}.")
        return False
    return True

def try_other_camera(current_index):
    # Try the other camera
    other_index = 1 if current_index == 0 else 0
    logging.getLogger().important(f"Switching to camera index {other_index}.")
    if initialize_camera(other_index):
        return other_index
    else:
        logging.error(f"Failed to open video device {other_index}.")
        return None

def take_pictures(step, is_product_change=False, retry=True):
    directory_suffix = "CIP" if is_product_change else step
    directory_path = os.path.join(BASE_IMAGE_SAVE_PATH, EQUIPMENT, directory_suffix)
    ensure_directory(directory_path)

    global cap
    global CAMERA_INDEX
    if cap is None or not cap.isOpened():
        logging.error("Video device is not initialized or has been closed.")
        return

    for _ in range(10):
        cap.read()

    try:
        for i in range(NUMBER_OF_PICTURES):
            ret, frame = cap.read()
            if ret:
                timestamp = time.strftime("%d.%m.%Y_%H.%M.%S")
                image_path = os.path.join(directory_path, f'{timestamp}_{i}.png')
                try:
                    cv2.imwrite(image_path, frame)
                    logging.getLogger().important(f"Image successfully saved: {image_path}")
                except Exception as e:
                    logging.getLogger().important(f"Failed to save image: {e}")
                    raise e  # Raise exception to trigger retry mechanism
                time.sleep(0.2)
            else:
                logging.getLogger().important("Failed to capture image")
                raise Exception("Failed to capture image")  # Trigger retry mechanism
    except Exception as e:
        logging.getLogger().important(f"Error during image capture or save: {e}")
        if retry:
            logging.getLogger().important(f"Retrying with a different camera.")
            CAMERA_INDEX = try_other_camera(CAMERA_INDEX)
            if CAMERA_INDEX is not None:
                take_pictures(step, is_product_change, retry=False)  # Retry once with the other camera
    finally:
        print("fim")
        
def parse_valid_steps(config):
    steps = {}
    entries = config.split(',')
    for entry in entries:
        parts = entry.split(';')
        step = f"{float(parts[0]):.1f}"  # Format with one decimal place
        delay = float(parts[1])
        strategy = int(parts[2])
        steps[step] = {'delay': delay, 'strategy': strategy}
    return steps

valid_steps = parse_valid_steps(VALID_STEPS)
print("Valid steps loaded:", valid_steps)  # This should show how keys are formatted

class SubHandler(object):
    def __init__(self):
        self.last_value = None
        self.last_product_value = None
        self.active_timer = None
        self.last_strategy = None
        self.initial_step_change = False  # Flag to check if initial step change has occurred
        self.initial_product_change = False  # Flag to check if initial product change has occurred

    def handle_value_change(self, new_value):
        print("Handling value change for:", new_value)
        if self.active_timer:
            self.active_timer.cancel()
            self.active_timer = None
            logging.getLogger().important("Cancelled previous timer due to new valid step.")

        step_key = f"{float(new_value):.1f}"
        global step
        step = step_key
        step_info = valid_steps.get(step_key)
        print("Step info:", step_info)

        if not self.initial_step_change:
            self.initial_step_change = True  # Mark the first change
            self.last_value = new_value
            self.last_strategy = step_info['strategy'] if step_info else None
            return  # Skip processing for the first change

        # Check if exiting from Strategy 2
        if self.last_strategy == 2:
            if not step_info or step_info['strategy'] != 2:
                take_pictures(str(self.last_value))
            elif step_info['strategy'] == 2 and step_key != f"{float(self.last_value):.1f}":
                # Additional condition to handle transition between different Strategy 2 steps
                take_pictures(str(self.last_value))

        if step_info:
            strategy = step_info['strategy']
            delay = step_info['delay']
            if strategy == 1:
                if delay > 0:
                    self.active_timer = Timer(delay, lambda: take_pictures(step_key))
                    self.active_timer.start()
                else:
                    take_pictures(step_key)
            elif strategy == 2:
                # No action needed here if not entering from another Strategy 2 step
                pass
            elif strategy == 3:
                self.start_continuous_capture(delay)

        self.last_value = new_value
        self.last_strategy = step_info['strategy'] if step_info else None

    def start_continuous_capture(self, interval):
        first_enter = True
        def capture():
            nonlocal first_enter
            global step
            print(f"Current last_value: {self.last_value}, Target step: {step}")
            if float(self.last_value) == float(step) or first_enter:
                take_pictures(step)
                self.active_timer = Timer(interval, capture)
                self.active_timer.start()
                first_enter = False
            else:
                print("Stopping capture as conditions are not met.")
                self.active_timer.cancel()

        capture()

    def handle_product_change(self, product_value):
        if not self.initial_product_change:  # Check if it's the first product change
            self.initial_product_change = True
            self.last_product_value = product_value  # Set initial product value
            return  # Skip further processing until the next product change

        # Now handle changes only if last_product_value is not None
        if self.last_product_value is not None and product_value >= 0 and self.last_product_value < 0:
            take_pictures("any_value", is_product_change=True)

        self.last_product_value = product_value  # Update last_product_value for next change

def connect_to_opcua():
    while True:
        client = Client(OPC_SERVER_URL)
        try:
            client.connect()
            logging.getLogger().important(f"Connected to {OPC_SERVER_URL}")
            tag_node = client.get_node(TAG_NAME)
            handler = SubHandler()
            sub = client.create_subscription(500, handler)
            sub.subscribe_data_change(tag_node)
            logging.getLogger().important("Subscription created, waiting for events...")
            
            # Infinite loop to keep script running
            while True:
                try:
                    # Test the connection by reading a value
                    tag_node.get_value()
                    time.sleep(1)
                except ua.UaStatusCodeError:
                    logging.error("Lost connection to OPA UA server. Trying to reconect...")
                    break
        except Exception as e:
            logging.exception(f"An error occurred")
            time.sleep(15)  # Wait for 15 seconds before trying to reconnect
        finally:
            try:
                client.disconnect()
                logging.getLogger().important("Client disconnected.")
            except:
                pass

def main():
    global CAMERA_INDEX
    if not initialize_camera(CAMERA_INDEX):
        CAMERA_INDEX = try_other_camera(CAMERA_INDEX)
    connect_to_opcua()
    cap.release()

if __name__ == '__main__':
    main()
