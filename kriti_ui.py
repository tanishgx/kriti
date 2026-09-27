"""
kriti_ui.py — shared terminal helpers (blessed Terminal, clear, colour).
Imported by every module that prints, so none of them need kriti.py.
"""

from blessed import Terminal

term = Terminal()

def clr():
    print(term.clear(), end="")

def color(text, c):
    mapping = {
        "green":        term.green,
        "cyan":         term.cyan,
        "yellow":       term.yellow,
        "magenta":      term.magenta,
        "bright_green": term.bright_green,
        "bright_red":   term.bright_red,
        "lime":         term.bright_green,
        "dim":          term.dim,
        "bold":         term.bold,
        "red":          term.red,
    }
    fn = mapping.get(c, lambda x: x)
    return fn(text) + term.normal

