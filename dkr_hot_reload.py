# TODO:
# * Support Linux! (Only Windows is supported at the moment)
# * Download UNFLoader automatically, instead of including the binary in the repo?
# * Allow for user-changable colors?

from winpty import PtyProcess
import os
from appJar import gui
import threading
import re

# Options
PROGRAM_TITLE = "DKR USB HOT-RELOAD TOOL"
HOT_RELOAD_CHECK_INTERVAL = 1.0 # Check for updated code every second.
LAST_ROM_PATH_SAVE = 'lastRomPath.txt'
UNFLOADER = 'UNFLoader.exe'

# Status colors
COLOR_NORMAL = '#E0E0E0'
COLOR_GOOD = '#44C044'
COLOR_BAD = '#F08888'
COLOR_ACTION = '#F0F888'

NEWLINE = '\r\n'

ROM_PATH = ""
HOT_RELOAD_PATH = ""

hotReloadLastTimestamp = 0
reconnectAttempts = 0
proc = None
currentStatus = ""
errorText = ""

ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def escape_ansi(line):
    return ansi_escape.sub('', line)

def get_cmd():
    return [UNFLOADER, "-b", "-r", ROM_PATH, "-d"]

def disable_user_input():
    app.disableEntry("userInput")
    app.disableButton("sendUserInput")

def enable_user_input():
    app.enableEntry("userInput")
    app.enableButton("sendUserInput")

def set_status_text_and_color(newStatus, color):
    app.setLabel("status", currentStatus)
    app.setLabelFg("status", color)

def set_status(newStatus, color=COLOR_NORMAL):
    global currentStatus
    currentStatus = newStatus
    app.queueFunction(set_status_text_and_color, currentStatus, color)
    
def simplify_text(text):
    if 'Error:' in text:
        text = text[text.rindex('Error:'):]
    text = escape_ansi(text)
    if '\x07' in text:
        text = text[text.rindex('\x07')+1:]
    return text
    
def status_ready():
    set_status("Ready", COLOR_GOOD)
    enable_user_input()
    check_for_hot_reload()
    
def handle_line(line):
    global reconnectAttempts
    lineLower = line.lower()
    
    # TODO: Clean this up!
    if lineLower.startswith('uploading rom'):
        reconnectAttempts = 0 # Reset this
        set_status("Uploading ROM (Please wait...)")
    elif lineLower.startswith('debug mode started'):
        status_ready()
    elif lineLower.endswith('autodetected' + NEWLINE):
        output_line(line)
    elif lineLower.startswith('sent command'):
        output_line(line)
    elif lineLower.startswith('send_hotreload'):
        set_status("Hot reloading ROM (Please wait...)", COLOR_ACTION)
        proc.write("@"+HOT_RELOAD_PATH+"@" + NEWLINE)
    elif lineLower.startswith('hotreload_done'):
        status_ready()
    elif lineLower.startswith('error:'):
        output_line(line)
        
def overwrite_output(newOutput):
    # Can't just overwrite a text area unfortunately. 
    app.clearTextArea("output")
    app.setTextArea("output", newOutput)

def check_if_output_line_is_duplicate(line):
    outputText = app.getTextArea("output")
    if NEWLINE in outputText:
        try:
            line = line[:-len(NEWLINE)]
            startIndex = 0
            endIndex = outputText.rindex(NEWLINE)
            if outputText.count(NEWLINE) > 1:
                startIndex = outputText.rindex(NEWLINE, 0, -len(NEWLINE)) + len(NEWLINE)
            lastLine = outputText[startIndex:endIndex]
            if lastLine == line:
                newCount = 2
            elif lastLine.startswith(line + " ("):
                newCount = int(lastLine[lastLine.rindex("(")+1:lastLine.rindex(")")]) + 1
            else:
                return False
            outputText = outputText[:startIndex] + line + " (" + str(newCount) + ")" + NEWLINE
            app.queueFunction(overwrite_output, outputText)
            return True
        except ValueError:
            pass
    return False

def output_line(line):
    if len(line) == 0:
        return
    if not check_if_output_line_is_duplicate(line):
        app.queueFunction(app.setTextArea, "output", line)

def handle_input():
    while proc.isalive():
        try:
            line = proc.readline()
            line = simplify_text(line)
            print(line.encode('utf-8'))
            handle_line(line)
        except (EOFError, ConnectionAbortedError):
            break
    
def upload_input(userInput):
    global proc
    if(len(userInput) < 1):
        return
    if not (userInput[0] == '@' and userInput[-1] == '@'):
        while (len(userInput) % 4) != 3: # Pad out input to be 4 byte aligned minus 1.
            userInput += '_'
    proc.write(userInput + NEWLINE)
    userInput = ''

def force_exit(success=True):
    global proc
    proc.close()
    print('fin.')
    exit()
    
def try_reconnect():
    global reconnectAttempts
    reconnectAttempts += 1
    set_status("Reconnecting... (" + str(reconnectAttempts) + " attempt" + ("s" if reconnectAttempts != 1 else "") + " so far)")
    app.after(int(min(reconnectAttempts, 5) * 500) + 1000, start_UNFLoader)
    
def disconnected(success):
    global proc
    set_status("Disconnected", COLOR_BAD)
    disable_user_input()
    proc = None
    app.after(1500, try_reconnect) # Wait 1.5 seconds before trying to reconnect.
    
def send_user_input():
    try:
        upload_input(app.getEntry("userInput"))
    except EOFError:
        pass
    app.setEntry("userInput", "") # Clear input
        
def check_hotreload_timestamp():
    global hotReloadLastTimestamp
    if os.path.exists(HOT_RELOAD_PATH):
        timestamp = os.stat(HOT_RELOAD_PATH).st_mtime
        if (hotReloadLastTimestamp < timestamp) and (hotReloadLastTimestamp != 0):
            output_line('Hot reload!' + NEWLINE)
            upload_input('hot')
            hotReloadLastTimestamp = timestamp
            return True
        hotReloadLastTimestamp = timestamp
    return False
            
        
def check_for_hot_reload():
    if currentStatus == "Ready":
        check_hotreload_timestamp()
        app.after(int(HOT_RELOAD_CHECK_INTERVAL * 1000), check_for_hot_reload) # Call this function again after the time has elapsed.
        
def start_UNFLoader():
    global proc
    if proc != None:
        return
    proc = PtyProcess.spawn(get_cmd())
    set_status("Started")
    app.threadCallback(handle_input, disconnected)
    
def set_rom_path(newPath):
    global ROM_PATH, HOT_RELOAD_PATH
    ROM_PATH = newPath
    HOT_RELOAD_PATH = ROM_PATH[:ROM_PATH.rindex('/')+1] + "dkr_code.bin"
    try:
        # Try to include the repo folder name if avaliable.
        repoPath = ROM_PATH[ROM_PATH.rindex("/", 0, ROM_PATH.rindex("/build/"))+1:]
        app.setEntry("romPath", repoPath)
    except:
        # Otherwise just do the rom name.
        app.setEntry("romPath", ROM_PATH[ROM_PATH.rindex('/')+1:])
    
def open_rom_path():
    path = app.openBox(title="Open ROM", dirName=None, fileTypes=[('ROM', '.z64'), ('Binary', '.bin')], asFile=False, parent=None, multiple=False, mode='r')
    if len(path) == 0:
        return # User cancelled
    set_rom_path(path)
    open(LAST_ROM_PATH_SAVE, 'w').write(path)
    start_UNFLoader()

MAX_NUM_COLUMNS = 2

def gui_init_status(rowNum):
    app.setStretch("both")
    app.setSticky("nesw")
    app.addLabel("status", '', rowNum, 0, MAX_NUM_COLUMNS)
    
def gui_init_rom_input(rowNum):
    app.setPadding([5,5])
    app.setStretch("column")
    app.addEntry("romPath", rowNum, 0)
    app.disableEntry("romPath")
    app.setEntry("romPath", ROM_PATH)
    app.setEntryAnchor("romPath", "center")
    app.setEntryDefault("romPath", "No ROM selected.")
    app.addButton("romPathButton", open_rom_path, rowNum, 1)
    app.setButton("romPathButton", "Browse...")
    
def gui_init_output(rowNum):
    app.setPadding([0,0])
    app.setStretch("both")
    app.addScrolledTextArea("output", rowNum, 0, MAX_NUM_COLUMNS)
    app.disableTextArea("output") # Prevent user from typing in the output area.
    
def gui_init_userinput(rowNum):
    app.setPadding([10,20])
    app.setStretch("column")
    app.addEntry("userInput", rowNum, 0)
    app.addButton("sendUserInput", send_user_input, rowNum, 1)
    app.setEntrySubmitFunction("userInput", send_user_input) # Send user input if user presses <Enter>.
    app.setButton("sendUserInput", "Send")
    disable_user_input()

def gui_init():
    global proc
    app.setTitle(PROGRAM_TITLE)
    app.setBg("#666666")
    gui_init_status(0)
    gui_init_rom_input(1)
    gui_init_output(2)
    gui_init_userinput(3)
    
    if not os.path.exists(UNFLOADER):
        app.errorBox("UNFLoader not found", UNFLOADER + " could not be found in the working directory. Aborting!")
        exit()
    
    if os.path.exists(LAST_ROM_PATH_SAVE):
        prevRomPath = open(LAST_ROM_PATH_SAVE, 'r').read()
        if app.yesNoBox('Use previous ROM?', 'Reload "' + prevRomPath + '"?'):
            set_rom_path(prevRomPath)
    
    if len(ROM_PATH) == 0:
        set_status("Please select a ROM file.")
    else:
        start_UNFLoader()

app = gui(handleArgs=False)
app.setSize(500, 300)
app.setStartFunction(gui_init)
app.go()
