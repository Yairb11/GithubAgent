from PyQt6.QtCore import pyqtSignal
def get_promot(prompt_name):
    """Gets prompt name and returns the full prompt from the saved {prompt}.txt file

    Args:
        prompt_name (string): prompt name

    Returns:
        string: full prompt
    """
    prompt = ""
    with open(f"prompts/{prompt_name}.txt", "r", encoding="utf-8") as file:
        prompt = file.read()
    return prompt

def show_text(text, signal:pyqtSignal = None, override = False):
    """Show the text in the right format in the right place.
    if you connect this to my ui, it would show the correct things in the correct QWidgets
    if not, it would print you in the terminal

    Args:
        text (str): text
        signal (pyqtSignal, optional): connection to my ui. Defaults to None.
        override (bool, optional): if it prints it in the terminal, should it start new line or not. Defaults to False.
    """
    if not signal:
        if override:
            print(text)
            return
        print(text, end="", flush=True)
        return
    signal.emit(text)