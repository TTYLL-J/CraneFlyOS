# CraneFlyOS

![csplash](https://github.com/user-attachments/assets/4b0bbe79-f4e5-48ff-94d1-7af29d28ffa1)


A lightweight, menu-driven operating system for PiPico with the 1.3" OLED display.


# Core System
- **Interactive Menu System** - Navigate through commands using two-button controls

# Subprocess Management
- Execute external Python programs with exit handling
- Not so clean process termination *but, it works

# Hardware Requirements

- Raspberry Pi Pico or compatible MicroPython board
- Waveshare OLED hat (SSD1306 or compatible, 1.3" 128x64 specifically)

# Installation

1. Flash MicroPython to your device
2. Copy main.py, convert.py, ssd1306.py to the root directory of your device
3. The OS will automatically start on boot

# Button Controls

- **BTN1 (short press)** - Scroll through menu options / Navigate to next item
- **BTN2 (short press)** - Select / OK / Confirm
- **BTN1 hold + BTN2 tap** - Scroll down in content
- **BTN2 hold + BTN1 tap** - Scroll up in content
- **Both buttons (short press)** - Context-dependent (Back to menu in cbin mode)
- **Both buttons (long press)** - Reboot system

# Subprocess Controls
When running external programs:
- **Both buttons (short press)** - Exit current process
- **Both buttons (long press)** - Force reboot

## Menu Commands

![Cmenu](https://github.com/user-attachments/assets/cf565f0d-d9b7-4d87-8f01-30081a13d16e)


# cfetch
Displays system information
- Serial ID
- Processor Frequency
- CPU temp
- Ram (placeholder text in code)

# ctop
Quazi system monitoring:
- Uptime (hours, minutes, seconds)
- Total memory
- Memory usage statistics
- Current memory utilization percentage

# cbin
File browser and executor:
- Execute .py files on the pico
- Automatic exclusion of main.py (the OS itself, although you could probably run a copy within a copy within a copy....)

# reboot
Restart the system

# Screensaver
- For fun!

## Creating Programs for CraneFly OS

External programs can integrate with the OS for exit code:

# Check if user requested exit
if should_exit():
    # Clean up and exit
    break

# Or use the function directly
if check_exit():
    # Clean up and exit
    break

These functions are automatically injected into the namespace when your program runs through the cbin though, they may conflict with other code.


## Contributing

Contributions are welcome! Areas for improvement:
- Additional system commands
- MOAR screensavers/screensaver selection
- File management operations (copy, delete, rename)
- Configuration system
- Journal or To-Do notepad function
- Help system implementation
- Network connectivity features (pico W)

### v1.0.1 Inital Release
- 30-second inactivity timeout screensaver (this is where the .1 comes from!)
- Initial release
- Core OS functionality
- File browser (cbin)
- System monitoring tools
- Subprocess management

---

**Note**: This OS is designed to run as main.py on the Pi Pico. It will automatically start on boot and provide a persistent menu interface for system interaction.
