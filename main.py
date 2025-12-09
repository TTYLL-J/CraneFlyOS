from machine import Pin, SPI
import framebuf
import time
import machine
import sys
import gc
import os
import _thread

# ============================================================================
# PIN DEFINITIONS
# ============================================================================
CS = 9
SCK = 10
MOSI = 11
DC = 8
RST = 12
BTN1 = 15
BTN2 = 17

# ============================================================================
# GLOBAL PROCESS CONTROL
# ============================================================================
class ProcessControl:
    """Global flag for subprocess termination"""
    should_exit = False
    lock = _thread.allocate_lock()
    
    @classmethod
    def request_exit(cls):
        with cls.lock:
            cls.should_exit = True
    
    @classmethod
    def clear_exit(cls):
        with cls.lock:
            cls.should_exit = False
    
    @classmethod
    def check_exit(cls):
        with cls.lock:
            return cls.should_exit

# ============================================================================
# OLED DRIVER 
# ============================================================================
class OLED_1inch3(framebuf.FrameBuffer):
    def __init__(self):
        self.width = 128
        self.height = 64
        self.rotate = 0
        self.cs = Pin(CS, Pin.OUT)
        self.rst = Pin(RST, Pin.OUT)
        self.cs(1)
        self.spi = SPI(1, 20000000, polarity=0, phase=0, sck=Pin(SCK), mosi=Pin(MOSI), miso=None)
        self.dc = Pin(DC, Pin.OUT)
        self.dc(1)
        self.buffer = bytearray(self.height * self.width // 8)
        super().__init__(self.buffer, self.width, self.height, framebuf.MONO_HMSB)
        self.init_display()
        self.white = 0xffff
        self.balck = 0x0000
    def write_cmd(self, cmd):
        self.cs(1)
        self.dc(0)
        self.cs(0)
        self.spi.write(bytearray([cmd]))
        self.cs(1)
    def write_data(self, buf):
        self.cs(1)
        self.dc(1)
        self.cs(0)
        self.spi.write(bytearray([buf]))
        self.cs(1)
    def init_display(self):
        self.rst(1)
        time.sleep(0.001)
        self.rst(0)
        time.sleep(0.01)
        self.rst(1)
        for cmd in (
            0xAE, 0x00, 0x10, 0xB0, 0xDC, 0x00, 0x81, 0x6F, 0x21,
            0xA1 if self.rotate == 180 else 0xA0,
            0xC0, 0xA4, 0xA6, 0xA8, 0x3F, 0xD3, 0x60, 0xD5, 0x41,
            0xD9, 0x22, 0xDB, 0x35, 0xAD, 0x8A, 0xAF
        ):
            self.write_cmd(cmd)
    def show(self):
        self.write_cmd(0xB0)
        for page in range(0, 64):
            self.column = page if self.rotate == 180 else 63 - page
            self.write_cmd(0x00 + (self.column & 0x0F))
            self.write_cmd(0x10 + (self.column >> 4))
            for num in range(0, 16):
                self.write_data(self.buffer[page * 16 + num])

# ============================================================================
# BUTTON FUNCTIONS
# ============================================================================
class ButtonHandler:
    def __init__(self, pin1, pin2):
        self.btn1 = Pin(pin1, Pin.IN, Pin.PULL_UP)
        self.btn2 = Pin(pin2, Pin.IN, Pin.PULL_UP)
        self.long_press_ms = 800
        self.debounce_ms = 50
        
    def get_input(self):
        """
        New button mapping:
        - btn1 short: scroll through options (next)
        - btn2 short: OK/select
        - btn1 hold + btn2 short: scroll down in content
        - btn2 hold + btn1 short: scroll up in content
        - both short: show help (future feature)
        - both long: reboot system
        """
        btn1_pressed = not self.btn1.value()
        btn2_pressed = not self.btn2.value()
        
        if not btn1_pressed and not btn2_pressed:
            return None
            
        time.sleep_ms(self.debounce_ms)
        
        # Check if both pressed
        if btn1_pressed and btn2_pressed:
            press_start = time.ticks_ms()
            # Wait for release or long press
            while not self.btn1.value() or not self.btn2.value():
                if time.ticks_diff(time.ticks_ms(), press_start) > self.long_press_ms:
                    # Long press both - reboot
                    while not self.btn1.value() or not self.btn2.value():
                        time.sleep_ms(10)
                    return 'both_long'
                time.sleep_ms(10)
            # Short press both - help
            return 'both_short'
        
        # Check for hold + tap combinations
        if btn1_pressed:
            press_start = time.ticks_ms()
            # Check if btn1 is held
            while not self.btn1.value():
                # Check if btn2 is tapped while btn1 held
                if not self.btn2.value():
                    time.sleep_ms(self.debounce_ms)
                    while not self.btn2.value():
                        time.sleep_ms(10)
                    # Wait for btn1 release
                    while not self.btn1.value():
                        time.sleep_ms(10)
                    return 'btn1_hold_btn2_tap'  # Scroll down
                
                # Timeout for hold detection
                if time.ticks_diff(time.ticks_ms(), press_start) > self.long_press_ms:
                    break
                time.sleep_ms(10)
            
            # Wait for btn1 release
            while not self.btn1.value():
                time.sleep_ms(10)
            return 'btn1_short'  # Next option
        
        if btn2_pressed:
            press_start = time.ticks_ms()
            # Check if btn2 is held
            while not self.btn2.value():
                # Check if btn1 is tapped while btn2 held
                if not self.btn1.value():
                    time.sleep_ms(self.debounce_ms)
                    while not self.btn1.value():
                        time.sleep_ms(10)
                    # Wait for btn2 release
                    while not self.btn2.value():
                        time.sleep_ms(10)
                    return 'btn2_hold_btn1_tap'  # Scroll up
                
                # Timeout for hold detection
                if time.ticks_diff(time.ticks_ms(), press_start) > self.long_press_ms:
                    break
                time.sleep_ms(10)
            
            # Wait for btn2 release
            while not self.btn2.value():
                time.sleep_ms(10)
            return 'btn2_short'  # OK/Select
        
        return None

# ============================================================================
# DISPLAY MANAGER (to help scroll and stop words from falling off screen)
# ============================================================================
class Display:
    def __init__(self, oled):
        self.oled = oled
        self.line_height = 10
        self.max_lines = 6
        self.char_width = 8
        self.max_chars = 16  # 128 pixels / 8 pixels per char
        
    def clear(self):
        self.oled.fill(0)
        
    def wrap_text(self, text):
        """Wrap text to fit screen width (16 chars max per line)"""
        lines = []
        words = text.split(' ')
        current_line = ""
        
        for word in words:
            # If word itself is longer than max_chars, split it
            if len(word) > self.max_chars:
                if current_line:
                    lines.append(current_line.strip())
                    current_line = ""
                # Split long word across lines
                for i in range(0, len(word), self.max_chars):
                    lines.append(word[i:i+self.max_chars])
            elif len(current_line) + len(word) + 1 <= self.max_chars:
                current_line += word + " "
            else:
                lines.append(current_line.strip())
                current_line = word + " "
        
        if current_line:
            lines.append(current_line.strip())
        
        return lines
    
    def draw_text(self, text, x, y):
        self.oled.text(text, x, y, 1)
        
    def draw_lines(self, lines, scroll_offset=0, highlight_index=-1):
        """Draw lines with optional scrolling and highlighting"""
        self.clear()
        start_line = scroll_offset
        visible_lines = lines[start_line:start_line + self.max_lines]
        
        for i, line in enumerate(visible_lines):
            # Truncate to max chars
            display_line = line[:self.max_chars]
            y_pos = i * self.line_height
            
            # Highlight if this is the selected line
            if i + start_line == highlight_index:
                # Draw selection indicator
                self.oled.text(">", 0, y_pos, 1)
                self.oled.text(display_line, 10, y_pos, 1)
            else:
                self.oled.text(display_line, 0, y_pos, 1)
        
        self.oled.show()

# ============================================================================
# SCREENSAVER
# ============================================================================
class Screensaver:
    def __init__(self, oled, display):
        self.oled = oled
        self.display = display
        self.frames = [
            [" (o)", " (|)",],
            ["(\\o/)", "(/|\\)",],
        ]
        self.current_frame = 0
        self.x = 64
        self.y = 32
        self.dx = 1
        self.dy = 1
        
    def get_random_direction(self):
        """Generate random direction changes"""
        import random
        return random.choice([-1, 0, 1])
        
    def update(self):
        """Update screensaver animation"""
        # Clear screen
        self.display.clear()
        
        # Draw current frame
        frame = self.frames[self.current_frame]
        for i, line in enumerate(frame):
            self.oled.text(line, self.x, self.y + (i * 8), 1)
        
        self.oled.show()
        
        # Update position with wandering
        self.x += self.dx
        self.y += self.dy
        
        # Bounce off edges (accounting for text width)
        max_width = max(len(line) for line in frame) * 8
        max_height = len(frame) * 8
        
        if self.x <= 0 or self.x + max_width >= 128:
            self.dx = -self.dx
            self.dx += self.get_random_direction()
            self.dx = max(-2, min(2, self.dx))  # Limit speed
            if self.dx == 0:
                self.dx = 1
                
        if self.y <= 0 or self.y + max_height >= 64:
            self.dy = -self.dy
            self.dy += self.get_random_direction()
            self.dy = max(-2, min(2, self.dy))  # Limit speed
            if self.dy == 0:
                self.dy = 1
        
        # Keep in bounds
        self.x = max(0, min(128 - max_width, self.x))
        self.y = max(0, min(64 - max_height, self.y))
        
        # Advance to next frame
        self.current_frame = (self.current_frame + 1) % len(self.frames)

# ============================================================================
# SUBPROCESS MANAGER - To run programs other than CraneFly Terminal
# ============================================================================
class SubprocessManager:
    def __init__(self, buttons):
        self.buttons = buttons
        self.running = False
        self.process_thread = None
        
    def monitor_exit_buttons(self):
        """Monitor buttons for exit request in a separate thread"""
        while self.running:
            action = self.buttons.get_input()
            if action == 'both_short':
                # Request process exit
                ProcessControl.request_exit()
                break
            elif action == 'both_long':
                # Force reboot
                machine.reset()
            time.sleep_ms(50)
    
    def execute_file(self, filepath, display, oled):
        """Execute a Python file with exit monitoring"""
        if not filepath.endswith('.py'):
            return ["Error:", "Not a .py file"]
        
        try:
            # Clear exit flag
            ProcessControl.clear_exit()
            self.running = True
            
            # Show execution message
            display.clear()
            display.draw_text("Running:", 0, 0)
            display.draw_text(filepath[-14:], 0, 10)
            display.draw_text("Both btns short:", 0, 20)
            display.draw_text("Exit process", 0, 30)
            display.draw_text("Both btns long:", 0, 40)
            display.draw_text("Reboot", 0, 50)
            oled.show()
            time.sleep(2)
            
            # Clear screen for the program
            display.clear()
            oled.show()
            
            # Start button monitor thread
            try:
                self.process_thread = _thread.start_new_thread(self.monitor_exit_buttons, ())
            except:
                # Threading not available, fall back to blocking execution
                pass
            
            # Read and prepare the file
            with open(filepath, 'r') as f:
                code = f.read()
            
            # Inject exit checking capability
            # Create a namespace with exit checking function
            namespace = {
                '__name__': '__main__',
                'check_exit': ProcessControl.check_exit,
                'should_exit': lambda: ProcessControl.check_exit()
            }
            
            # Execute the file
            exec(code, namespace)
            
            # Cleanup
            self.running = False
            ProcessControl.clear_exit()
            
            return ["Process exited", "normally"]
            
        except KeyboardInterrupt:
            self.running = False
            ProcessControl.clear_exit()
            return ["Process", "interrupted"]
        except Exception as e:
            self.running = False
            ProcessControl.clear_exit()
            error_msg = str(e)
            return ["Exec Error:", error_msg[:40], error_msg[40:80] if len(error_msg) > 40 else ""]

# ============================================================================
# FILE SYSTEM BROWSER (CBIN)
# ============================================================================
class FileBrowser:
    def __init__(self, display):
        self.display = display
        self.current_path = "/"
        self.items = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.refresh_items()
        
    def refresh_items(self):
        """Scan current directory for files and folders"""
        self.items = []
        try:
            entries = os.listdir(self.current_path)
            for entry in sorted(entries):
                # Skip main.py (the OS itself)
                if entry == "main.py":
                    continue
                    
                full_path = self.current_path + ("" if self.current_path == "/" else "/") + entry
                
                # Check if it's a directory
                try:
                    os.listdir(full_path)
                    self.items.append({"name": entry, "type": "dir", "path": full_path})
                except:
                    # It's a file
                    self.items.append({"name": entry, "type": "file", "path": full_path})
            
            # Add parent directory option if not at root
            if self.current_path != "/":
                self.items.insert(0, {"name": "..", "type": "parent", "path": self._get_parent_path()})
                
        except Exception as e:
            self.items = [{"name": f"Error: {str(e)}", "type": "error", "path": ""}]
        
        # Reset selection
        self.selected_index = 0
        self.scroll_offset = 0
    
    def _get_parent_path(self):
        """Get parent directory path"""
        if self.current_path == "/":
            return "/"
        parts = self.current_path.rstrip("/").split("/")
        if len(parts) <= 1:
            return "/"
        return "/".join(parts[:-1]) or "/"
    
    def get_display_lines(self):
        """Generate display lines for current directory"""
        if not self.items:
            return ["(empty)"]
        
        lines = []
        for item in self.items:
            if item["type"] == "dir":
                lines.append(f"[D] {item['name']}")
            elif item["type"] == "parent":
                lines.append(f"[D] {item['name']}")
            elif item["type"] == "error":
                lines.append(item["name"])
            else:
                lines.append(item["name"])
        return lines
    
    def next_item(self):
        """Move to next item (loops)"""
        if self.items:
            self.selected_index = (self.selected_index + 1) % len(self.items)
            # Auto-scroll to keep selection visible
            if self.selected_index < self.scroll_offset:
                self.scroll_offset = self.selected_index
            elif self.selected_index >= self.scroll_offset + self.display.max_lines:
                self.scroll_offset = self.selected_index - self.display.max_lines + 1
    
    def scroll_down(self):
        """Scroll view down"""
        max_scroll = max(0, len(self.items) - self.display.max_lines)
        self.scroll_offset = min(self.scroll_offset + 1, max_scroll)
    
    def scroll_up(self):
        """Scroll view up"""
        self.scroll_offset = max(0, self.scroll_offset - 1)
    
    def get_selected_item(self):
        """Get currently selected item"""
        if self.items and 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None
    
    def enter_selected(self):
        """Enter directory or return file to execute"""
        item = self.get_selected_item()
        if not item:
            return None
            
        if item["type"] == "dir" or item["type"] == "parent":
            # Navigate into directory
            self.current_path = item["path"]
            self.refresh_items()
            return None
        elif item["type"] == "file":
            # Return file path for execution
            return item["path"]
        return None
    
    def show(self):
        """Display the file browser"""
        lines = self.get_display_lines()
        self.display.draw_lines(lines, self.scroll_offset, self.selected_index)

# ============================================================================
# MENU SYSTEM
# ============================================================================
class MenuSystem:
    def __init__(self, display):
        self.display = display
        self.menu_items = ['cfetch', 'ctop', 'cbin', 'reboot']
        self.selected_index = 0
        
    def get_menu_lines(self):
        """Generate menu display with selection indicator"""
        return self.menu_items
    
    def next_item(self):
        """Move to next menu item (loops)"""
        self.selected_index = (self.selected_index + 1) % len(self.menu_items)
    
    def get_selected(self):
        """Get currently selected menu item"""
        return self.menu_items[self.selected_index]
    
    def show(self):
        """Display the menu"""
        self.display.draw_lines(self.get_menu_lines(), 0, self.selected_index)

# ============================================================================
# COMMAND IMPLEMENTATIONS
# ============================================================================
class Commands:
    @staticmethod
    def cfetch():
        """System information (combines old cranefetch + version)"""
        uid = machine.unique_id().hex()
        freq = machine.freq() // 1000000
        temp = "N/A"
        
        try:
            sensor = machine.ADC(4)
            reading = sensor.read_u16() * 3.3 / 65535
            temp = f"{27 - (reading - 0.706) / 0.001721:.1f}C"
        except:
            pass
            
        return [
            "     CraneFly OS",
            "(\\0/)     v1.0.1",
            "(/|\)    ",
            "        ",
            "",
            f"ID:",
            f"{uid}",
            f"Freq: {freq}MHz",
            f"Temp: {temp}",
            f"RAM: 264KB",
        ]
    
    @staticmethod
    def ctop():
        """Combined system status (uptime + memory)"""
        # Uptime calculation
        ms = time.ticks_ms()
        secs = ms // 1000
        mins = secs // 60
        hours = mins // 60
        
        # Memory info
        gc.collect()
        free = gc.mem_free()
        alloc = gc.mem_alloc()
        total = free + alloc
        
        return [
            " === System === ",
            "",
            "Uptime:",
            f"  {hours}h {mins%60}m {secs%60}s",
            "",
            "Memory:",
            f"Total: {total}B",
            f"Used:  {alloc}B",
            f"Free:  {free}B",
            f"Usage: {alloc*100//total}%"
        ]
    
    @staticmethod
    def reboot():
        """reboot the system"""
        machine.reset()
        return ["rebooting..."]

# ============================================================================
# MAIN OS CLASS
# ============================================================================
class CraneFlyOS:
    def __init__(self):
        # Hardware initialization
        self.oled = OLED_1inch3()
        self.display = Display(self.oled)
        self.buttons = ButtonHandler(BTN1, BTN2)
        
        # System components
        self.menu = MenuSystem(self.display)
        self.commands = Commands()
        self.file_browser = FileBrowser(self.display)
        self.subprocess_mgr = SubprocessManager(self.buttons)
        self.screensaver = Screensaver(self.oled, self.display)
        
        # State management
        self.mode = 'menu'  # 'menu', 'output', 'cbin'
        self.output_lines = []
        self.scroll_offset = 0
        
        # Screensaver management
        self.screensaver_active = False
        self.last_activity_time = time.ticks_ms()
        self.screensaver_timeout = 30000  # 30 seconds in milliseconds
        
    def reset_screensaver_timer(self):
        """Reset the inactivity timer"""
        self.last_activity_time = time.ticks_ms()
        if self.screensaver_active:
            self.screensaver_active = False
            # Redraw current screen
            if self.mode == 'menu':
                self.menu.show()
    
    def check_screensaver(self):
        """Check if screensaver should activate"""
        if self.mode == 'menu' and not self.screensaver_active:
            elapsed = time.ticks_diff(time.ticks_ms(), self.last_activity_time)
            if elapsed >= self.screensaver_timeout:
                self.screensaver_active = True
    
    def show_boot_screen(self):
        """Display boot sequence"""
        lines = [
            "  CraneFly OS",
            "",
            "     (\\0/)                ",
            "     (/|\) ",
            "",
            "  ..Booting..   ",
            "",
        ]
        self.display.draw_lines(lines)
        time.sleep(2)
    
    def execute_command(self, cmd_name):
        """Execute a command and store output"""
        if cmd_name == 'cfetch':
            result = self.commands.cfetch()
            self.output_lines = result
            self.scroll_offset = 0
            self.mode = 'output'
        elif cmd_name == 'ctop':
            result = self.commands.ctop()
            self.output_lines = result
            self.scroll_offset = 0
            self.mode = 'output'
        elif cmd_name == 'cbin':
            # Enter file browser mode
            self.file_browser.refresh_items()
            self.mode = 'cbin'
        elif cmd_name == 'reboot':
            self.commands.reboot()
        else:
            self.output_lines = [f"Unknown: {cmd_name}"]
            self.scroll_offset = 0
            self.mode = 'output'
    
    def execute_file(self, filepath):
        """Execute a Python file using subprocess manager"""
        result = self.subprocess_mgr.execute_file(filepath, self.display, self.oled)
        self.output_lines = result
        self.scroll_offset = 0
        self.mode = 'output'
    
    def show_output(self):
        """Display command output with scrolling"""
        self.display.draw_lines(self.output_lines, self.scroll_offset)
    
    def handle_menu_input(self, action):
        """Handle button inputs in menu mode"""
        if action == 'btn1_short':  # Next option
            self.menu.next_item()
            self.menu.show()
        elif action == 'btn2_short':  # Select/OK
            selected = self.menu.get_selected()
            self.execute_command(selected)
            if self.mode == 'output':
                self.show_output()
            elif self.mode == 'cbin':
                self.file_browser.show()
        elif action == 'both_long':  # reboot
            machine.reset()
    
    def handle_output_input(self, action):
        """Handle button inputs in output mode"""
        if action == 'btn1_short':  # Back to menu
            self.mode = 'menu'
            self.menu.show()
        elif action == 'btn2_short':  # Also back to menu
            self.mode = 'menu'
            self.menu.show()
        elif action == 'btn1_hold_btn2_tap':  # Scroll down
            max_scroll = max(0, len(self.output_lines) - self.display.max_lines)
            self.scroll_offset = min(self.scroll_offset + 1, max_scroll)
            self.show_output()
        elif action == 'btn2_hold_btn1_tap':  # Scroll up
            self.scroll_offset = max(0, self.scroll_offset - 1)
            self.show_output()
        elif action == 'both_long':  # reboot
            machine.reset()
    
    def handle_cbin_input(self, action):
        """Handle button inputs in file browser mode"""
        if action == 'btn1_short':  # Next item
            self.file_browser.next_item()
            self.file_browser.show()
        elif action == 'btn2_short':  # Select/Enter
            file_to_exec = self.file_browser.enter_selected()
            if file_to_exec:
                # Execute the selected file
                self.execute_file(file_to_exec)
                if self.mode == 'output':
                    self.show_output()
            else:
                # Just navigated to a directory, refresh display
                self.file_browser.show()
        elif action == 'btn1_hold_btn2_tap':  # Scroll down
            self.file_browser.scroll_down()
            self.file_browser.show()
        elif action == 'btn2_hold_btn1_tap':  # Scroll up
            self.file_browser.scroll_up()
            self.file_browser.show()
        elif action == 'both_short':  # Back to menu
            self.mode = 'menu'
            self.menu.show()
        elif action == 'both_long':  # reboot
            machine.reset()
    
    def run(self):
        """Main OS loop"""
        self.show_boot_screen()
        self.menu.show()
        
        while True:
            # Check for screensaver activation
            self.check_screensaver()
            
            # Get button input
            action = self.buttons.get_input()
            
            # If there's input, reset screensaver
            if action:
                self.reset_screensaver_timer()
            
            # Handle screensaver mode
            if self.screensaver_active:
                self.screensaver.update()
                time.sleep_ms(200)  # Slower update for screensaver
                continue
            
            # Handle input based on current mode
            if self.mode == 'menu':
                if action:
                    self.handle_menu_input(action)
                    
            elif self.mode == 'output':
                if action:
                    self.handle_output_input(action)
                    
            elif self.mode == 'cbin':
                if action:
                    self.handle_cbin_input(action)
            
            time.sleep_ms(50)

# ============================================================================
# ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    os_instance = CraneFlyOS()
    os_instance.run()
