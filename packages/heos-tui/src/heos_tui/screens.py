"""Small modal dialogs."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList
from textual.widgets.option_list import Option


class _Dialog(ModalScreen):
    DEFAULT_CSS = """
    _Dialog { align: center middle; }
    _Dialog > Vertical { width: 60; height: auto; max-height: 80%; border: thick $primary; background: $surface; padding: 1 2; }
    _Dialog Label { margin-bottom: 1; }
    _Dialog Horizontal { height: auto; margin-top: 1; }
    _Dialog Button { margin-right: 2; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChoiceScreen(_Dialog):
    """Pick one of several labelled values; dismisses with the value (never None) or None."""

    def __init__(self, title: str, choices: list[tuple[str, object]]) -> None:
        super().__init__()
        self._title = title
        self._choices = choices

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(Text(self._title))
            yield OptionList(
                *[Option(Text(label), id=str(i)) for i, (label, _) in enumerate(self._choices)]
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._choices[int(event.option_id)][1])


class ConfirmScreen(_Dialog):
    BINDINGS = [("escape", "cancel", "No"), ("n", "cancel", "No"), ("y", "yes", "Yes")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(Text(self._question))
            with Horizontal():
                yield Button("Yes", id="yes", variant="primary")
                yield Button("No", id="no")

    def action_yes(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class PromptScreen(_Dialog):
    """Ask for one line of text; dismisses with the text, or None if cancelled/empty."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(Text(self._title))
            yield Input(id="text")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)


class AccountScreen(_Dialog):
    """HEOS account. Dismisses with ("in", user, password), ("out",) or None."""

    def __init__(self, username: str | None) -> None:
        super().__init__()
        self._username = username

    def compose(self) -> ComposeResult:
        with Vertical():
            if self._username:
                yield Label(Text(f"Signed in as {self._username}"))
                yield Button("Sign out", id="out", variant="warning")
            else:
                yield Label("Sign in to your HEOS account")
                yield Input(placeholder="Username (email)", id="user")
                yield Input(placeholder="Password", password=True, id="pw")
                yield Button("Sign in", id="in", variant="primary")

    def _submit(self) -> None:
        user = self.query_one("#user", Input).value.strip()
        pw = self.query_one("#pw", Input).value
        if user and pw:
            self.dismiss(("in", user, pw))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "user":
            self.query_one("#pw", Input).focus()
        else:
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "out":
            self.dismiss(("out",))
        else:
            self._submit()
