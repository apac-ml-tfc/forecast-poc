# Python Built-Ins:
import sys
from typing import Iterable, Union

# External Dependencies:
from IPython.display import display, HTML
import ipywidgets


widget_table = {}

def create_text_widget( name, placeholder, default_value="" ):
    if name in widget_table:
        widget = widget_table[name]
    if name not in widget_table:
        widget = ipywidgets.Text( description = name, placeholder = placeholder, value=default_value )
        widget_table[name] = widget
    display(widget)
    
    return widget


def generate_warnbox(
    msg_html: Union[str, Iterable[str]],
    context_html: Union[str, Iterable[str], None]=None,
    level: Union["warning", "danger"]="warning"
) -> HTML:
    """Generate an alert box ready to be display()ed in an IPython notebook

    Parameters
    ----------
    msg_html :
        String or iterable of strings (which will be joined with newline) with a short description of the
        alert/warning. Will be encapsulated in <strong> tags if not already starting/ending with < and >.
    context_html : (Optional)
        String or iterable of strings (which will be joined with newline) with additional information. Will
        be enclosed in a <div> tag to separate from the initial msg_html.
    level : (Optional)
        Level string compatible with notebook 'alert-...' formatting. Defaults to 'warning'.
    """
    # Consolidate iterables of str into strings:
    if not isinstance(msg_html, str):
        msg_html = "\n".join(msg_html)
    if context_html and not isinstance(context_html, str):
        context_html = "\n".join(context_html)

    # Emphasize msg_html to distinguish from extra context:
    if not (msg_html.startswith("<") and msg_html.endswith(">")):
        msg_html = f"<strong>{msg_html}</strong>"

    return HTML("".join((
        f'<div class="alert alert-{level}">',
        msg_html,
        f'<div>{context_html}</div>' if context_html else "",
        "</div>",
    )))


class StatusIndicator:
    def __init__(self):
        self.previous_status = None
        self.need_newline = False
        
    def update( self, status ):
        if self.previous_status != status:
            if self.need_newline:
                sys.stdout.write("\n")
            sys.stdout.write( status + " ")
            self.need_newline = True
            self.previous_status = status
        else:
            sys.stdout.write(".")
            self.need_newline = True
        sys.stdout.flush()

    def end(self):
        if self.need_newline:
            sys.stdout.write("\n")
