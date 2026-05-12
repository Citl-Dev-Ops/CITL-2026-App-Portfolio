# Custom hook override: do not exclude tkinter even if local Tcl probe fails.
# We bundle Tcl/Tk data manually in build script.

def pre_find_module_path(hook_api):
    return
