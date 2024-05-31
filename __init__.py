from typing import List, Callable, TypedDict, Dict, Union
import re
from aqt import gui_hooks, editor, mw
from aqt.operations import QueryOp
from anki.cards import Card
from anki.notes import Note
from aqt.qt import (
    QAction,
    QDialog,
    QLabel,
    QLineEdit,
    QDialogButtonBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QFormLayout,
    QPushButton,
    QHBoxLayout,
    QComboBox
)
from PyQt6.QtCore import Qt
import requests

# TODO: sort imports...

# packages_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "env/lib/python3.11/site-packages")
# print(packages_dir)
# sys.path.append(packages_dir)


class NoteTypeMap(TypedDict):
    fields: Dict[str, str]


class PromptMap(TypedDict):
    note_types: Dict[str, NoteTypeMap]


class Config:
    openai_api_key: str
    prompts_map: PromptMap
    openai_model: str  # TODO: type this

    def __getattr__(self, key: str) -> object:
        if not mw:
            raise Exception("Error: mw not found")

        return mw.addonManager.getConfig(__name__).get(key)

    def __setattr__(self, name: str, value: object) -> None:
        if not mw:
            raise Exception("Error: mw not found")

        old_config = mw.addonManager.getConfig(__name__)
        if not old_config:
            raise Exception("Error: no config found")

        old_config[name] = value
        mw.addonManager.writeConfig(__name__, old_config)


config = Config()


# Create an OpenAPI Client
class OpenAIClient:
    def __init__(self, config: Config):
        self.api_key = config.openai_api_key

    def get_chat_response(self, prompt: str):
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
            json={
                "model": config.openai_model,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

        resp = r.json()
        msg = resp["choices"][0]["message"]["content"]
        return msg


client = OpenAIClient(config)


def get_chat_response_in_background(prompt: str, field: str, on_success: Callable):
    if not mw:
        print("Error: mw not found")
        return

    op = QueryOp(
        parent=mw,
        op=lambda _: client.get_chat_response(prompt),
        success=lambda msg: on_success(msg, field),
    )

    op.run_in_background()


def get_prompt_fields_lower(prompt: str):
    pattern = r"\{\{(.+?)\}\}"
    fields = re.findall(pattern, prompt)
    return [field.lower() for field in fields]


# TODO: need to use this
def validate_prompt(prompt: str, note: Note):
    prompt_fields = get_prompt_fields_lower(prompt)

    all_note_fields = {field.lower(): value for field, value in note.items()}

    for prompt_field in prompt_fields:
        if prompt_field not in all_note_fields:
            return False

    return True


def interpolate_prompt(prompt: str, note: Note):
    # Bunch of extra logic to make this whole process case insensitive

    # Regex to pull out any words enclosed in double curly braces
    fields = get_prompt_fields_lower(prompt)
    pattern = r"\{\{(.+?)\}\}"

    # field.lower() -> value map
    all_note_fields = {field.lower(): value for field, value in note.items()}

    # Lowercase the characters inside {{}} in the prompt
    prompt = re.sub(pattern, lambda x: "{{" + x.group(1).lower() + "}}", prompt)

    # Sub values in prompt
    for field in fields:
        value = all_note_fields.get(field, "")
        prompt = prompt.replace("{{" + field + "}}", value)

    print("Processed prompt: ", prompt)
    return prompt


def async_process_note(note: Note, on_success: Callable, overwrite_fields=False):
    note_type = note.note_type()

    if not note_type:
        print("Error: no note type")
        return

    note_type_name = note_type["name"]
    field_prompts = config.prompts_map.get("note_types", {}).get(note_type_name, None)

    if not field_prompts:
        print("Error: no prompts found for note type")
        return

    # TODO: should run in parallel for cards that have multiple fields needing prompting.
    # Needs to be in a threadpool exec but kinda painful. Later.
    for field, prompt in field_prompts["fields"].items():
        # Don't overwrite fields that already exist
        if (not overwrite_fields) and note[field]:
            print(f"Skipping field: {field}")
            continue

        print(f"Processing field: {field}, prompt: {prompt}")

        prompt = interpolate_prompt(prompt, note)

        def wrapped_on_success(msg: str, target_field: str):
            note[target_field] = msg
            # Perform UI side effects
            on_success()
            print("Successfully ran in background")

        get_chat_response_in_background(prompt, field, wrapped_on_success)


def on_editor(buttons: List[str], e: editor.Editor):
    def fn(editor: editor.Editor):
        note = editor.note
        if not note:
            print("Error: no note found")
            return

        async_process_note(
            note=note, on_success=lambda: editor.loadNote(), overwrite_fields=True
        )

    button = e.addButton(cmd="Fill out stuff", func=fn, icon="!")
    buttons.append(button)


def on_review(card: Card):
    print("Reviewing...")
    note = card.note()

    def update_note():
        if not mw:
            print("Error: mw not found")
            return

        mw.col.update_note(note)
        card.load()
        print("Updated on review")

    async_process_note(note=note, on_success=update_note, overwrite_fields=False)


class AIFieldsOptionsDialog(QDialog):
    def __init__(self, config: Config):
        super().__init__()
        self.api_key_edit = None
        self.prompts_map = config.prompts_map
        self.remove_button = None
        self.table = None
        self.config = config
        self.selected_row = None

        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("🤖 AI Fields Options")
        self.setMinimumWidth(600)

        # Setup Widgets

        # Form
        api_key_label = QLabel("OpenAI API Key")
        api_key_label.setToolTip(
            "Get your API key from https://platform.openai.com/account/api-keys"
        )

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setText(config.openai_api_key)
        self.api_key_edit.setPlaceholderText("12345....")
        form = QFormLayout()
        form.addRow(api_key_label, self.api_key_edit)

        # Buttons
        # TODO: Need a restore defaults button
        table_buttons = QHBoxLayout()
        add_button = QPushButton("+")
        add_button.clicked.connect(self.on_add)
        self.remove_button = QPushButton("-")
        table_buttons.addWidget(self.remove_button)
        table_buttons.addWidget(add_button)

        standard_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )

        standard_buttons.accepted.connect(self.on_accept)
        standard_buttons.rejected.connect(self.on_reject)

        # Table
        self.table = self.create_table()
        self.update_table()

        # Set up layout

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.table)
        layout.addLayout(table_buttons)
        layout.addWidget(standard_buttons)

        self.update_buttons()
        self.setLayout(layout)

    def create_table(self):
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Note Type", "Field", "Prompt"])
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        # Wire up slots
        table.currentItemChanged.connect(self.on_row_selected)
        table.itemDoubleClicked.connect(self.on_row_double_clicked)

        return table

    def update_table(self):
        self.table.setRowCount(0)

        row = 0
        for note_type, field_prompts in self.prompts_map["note_types"].items():
            for field, prompt in field_prompts["fields"].items():
                print(field, prompt)
                self.table.insertRow(self.table.rowCount())
                items = [
                    QTableWidgetItem(note_type),
                    QTableWidgetItem(field),
                    QTableWidgetItem(prompt),
                ]
                for i, item in enumerate(items):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, i, item)
                row += 1


    def on_row_selected(self, current):
        if not current:
            self.selected_row = None
        else:
            self.selected_row = current.row()
        self.update_buttons()

    def on_row_double_clicked(self, item):
        print(f"Double clicked: {item.row()}")

    def update_buttons(self):
        if self.selected_row is not None:
            self.remove_button.setEnabled(True)
        else:
            self.remove_button.setEnabled(False)

    def on_add(self, row):
        print(row)
        prompt_dialog = QPromptDialog(self.prompts_map, self.on_update_prompts)
        result = prompt_dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            self.update_table()

    def on_accept(self):
        self.config.openai_api_key = self.api_key_edit.text()
        self.config.prompts_map = self.prompts_map
        self.accept()

    def on_reject(self):
        self.reject()

    def on_update_prompts(self, prompts_map: PromptMap):
        self.prompts_map = prompts_map


class QPromptDialog(QDialog):
    def __init__(
        self,
        prompts_map: Config,
        on_accept_callback: Callable,
        card_type: Union[str, None] = None,
        field: Union[str, None] = None,
        prompt: Union[str, None] = None,
    ):
        super().__init__()
        self.config = config
        self.on_accept_callback = on_accept_callback
        self.prompts_map = prompts_map
        self.card_type = card_type
        self.field = field
        self.prompt = prompt
        self.card_types: List[str] = []
        self.fields_for_card: List[str] = []
        self.field_combo_box = None

        self.setup_ui()


    def setup_ui(self):
        self.setWindowTitle("Set Prompt")
        self.card_types = self.get_card_types()
        card_combo_box = QComboBox()
        self.field_combo_box = QComboBox()
        self.field_combo_box.currentTextChanged.connect(self.on_field_selected)

        card_combo_box.addItems(self.card_types)

        card_combo_box.setCurrentText(self.card_type)
        card_combo_box.currentTextChanged.connect(self.on_card_type_selected)

        label = QLabel("Card Type")
        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addWidget(card_combo_box)
        layout.addWidget(self.field_combo_box)

        standard_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )

        standard_buttons.accepted.connect(self.on_accept)
        standard_buttons.rejected.connect(self.on_reject)

        prompt_label = QLabel("Prompt")
        self.prompt_text_box = QLineEdit()
        self.prompt_text_box.textChanged.connect(self.on_text_changed)
        self.prompt_text_box.setMinimumHeight(150)
        self.prompt_text_box.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.setLayout(layout)
        layout.addWidget(prompt_label)
        layout.addWidget(self.prompt_text_box)
        layout.addWidget(standard_buttons)


    def get_card_types(self):
        # Including this function in a little UI
        # class is a horrible violation of separation of concerns
        # but I won't tell anybody if you don't

        models = mw.col.models.all()
        return [model["name"] for model in models]

    def get_fields(self, card_type: str):
        if not card_type:
            return []
        model = mw.col.models.byName(card_type)
        return [field["name"] for field in model["flds"]]

    def on_field_selected(self, field: str):
        if not field:
            return
        self.field = field
        self.update_prompt()

    def on_card_type_selected(self, card_type: str):
        if not card_type:
            return
        self.card_type = card_type

        self.update_fields()
        self.update_prompt()

    def update_fields(self):
        if not self.card_type:
            return
        self.fields = self.get_fields(self.card_type)

        self.field_combo_box.clear()
        self.field_combo_box.addItems(self.fields)

    def update_prompt(self):
        if not self.field or not self.card_type:
            self.prompt_text_box.setText("")
            return

        prompt = self.prompts_map.get("note_types", {}).get(self.card_type, {}).get("fields", {}).get(self.field, "")
        self.prompt_text_box.setText(prompt)

    def on_text_changed(self, text: str):
        self.prompt = text

    def on_accept(self):
        if self.card_type and self.field and self.prompt:
            # IDK if this is gonna work on the config object? I think not...
            print(f"Trying to set prompt for {self.card_type}, {self.field}, {self.prompt}")
            if not self.prompts_map["note_types"].get(self.card_type):
                self.prompts_map["note_types"][self.card_type] = {"fields": {}}
            self.prompts_map["note_types"][self.card_type]["fields"][self.field] = self.prompt
            self.on_accept_callback(self.prompts_map)
        self.accept()

    def on_reject(self):
        self.reject()



def on_options():
    dialog = AIFieldsOptionsDialog(config)
    dialog.exec()


def on_main_window():
    # Add options to Anki Menu
    options_action = QAction("AI Fields Options...", mw)
    options_action.triggered.connect(on_options)
    mw.form.menuTools.addAction(options_action)

    # TODO: do I need a profile_will_close thing here?
    print("Loaded")


gui_hooks.editor_did_init_buttons.append(on_editor)
# TODO: I think this should be 'card did show'?
gui_hooks.reviewer_did_show_question.append(on_review)
gui_hooks.main_window_did_init.append(on_main_window)
