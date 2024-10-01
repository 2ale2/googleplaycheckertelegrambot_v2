from enum import Enum

FOUND_AND_VALID = 0
FOUND_AND_INVALID = -1
NOT_FOUND = -2


class FirstBootConfigFileCheck:
    def __init__(self, code, message_data):
        self.code = code
        self.message_data = message_data

    def get_code(self):
        return self.code

    def get_message_data(self):
        return self.message_data


class ValidateResult:
    def __init__(self, field, code, message):
        self.field = field
        self.code = code
        self.message = message

    def get_code(self):
        return self.code

    def get_message(self):
        return self.message

    def __repr__(self):
        return f'CheckResult(field={self.field}, code={self.code}, message={self.message})'


class ValidateIntervalOutcome(ValidateResult):
    SUCCESS = 0
    INVALID_FORMAT = -1
    MISSING_VALUES = -2
    NON_POSITIVE_VALUES = -3

    @staticmethod
    def get_outcome(code, field='default_interval'):
        # noinspection PyShadowingNames
        messages = {
            ValidateIntervalOutcome.SUCCESS: f"Valore '{field}' valido",
            ValidateIntervalOutcome.INVALID_FORMAT: f"Usa il formato indicato per '{field}'",
            ValidateIntervalOutcome.MISSING_VALUES: f"Valori mancanti in '{field}'",
            ValidateIntervalOutcome.NON_POSITIVE_VALUES: f"Valori negativi in '{field}'",
        }
        message = messages.get(code, 'Errore Sconosciuto')
        return ValidateResult(field, code, message)


class ValidateSendOnCheckOutcome(ValidateResult):
    SUCCESS = 0
    INVALID_TYPE = -4

    @staticmethod
    def get_outcome(code, field='default_send_on_check'):
        # noinspection PyShadowingNames
        messages = {
            ValidateSendOnCheckOutcome.SUCCESS: f"Valore '{field}' valido",
            ValidateSendOnCheckOutcome.INVALID_TYPE: f"'{field}' deve essere un booleano"
        }
        message = messages.get(code, 'Errore Sconosciuto')
        return ValidateResult(field, code, message)


class ValidateAppConfiguration(ValidateResult):
    SUCCESS = 0
    INVALID_TYPE = -5
    MISSING_VALUES = -6
    INVALID_LINK = -7
    INTERVAL_INVALID_FORMAT = ValidateIntervalOutcome.INVALID_FORMAT
    INTERVAL_MISSING_VALUES = ValidateIntervalOutcome.MISSING_VALUES
    INTERVAL_NON_POSITIVE_VALUES = ValidateIntervalOutcome.NON_POSITIVE_VALUES
    SEND_ON_CHECK_INVALID_TYPE = ValidateSendOnCheckOutcome.INVALID_TYPE

    @staticmethod
    def from_interval_outcome(code):
        if code == ValidateAppConfiguration.INTERVAL_INVALID_FORMAT:
            return ValidateIntervalOutcome.INVALID_FORMAT
        if code == ValidateAppConfiguration.INTERVAL_MISSING_VALUES:
            return ValidateIntervalOutcome.MISSING_VALUES
        if code == ValidateAppConfiguration.INTERVAL_NON_POSITIVE_VALUES:
            return ValidateIntervalOutcome.NON_POSITIVE_VALUES

    @staticmethod
    def get_outcome(code):
        # noinspection PyShadowingNames
        messages = {
            ValidateAppConfiguration.SUCCESS: "App valida",
            ValidateAppConfiguration.INVALID_TYPE: "L'app deve essere un dizionario",
            ValidateAppConfiguration.MISSING_VALUES: "Il dizionario deve contenere 'link', 'interval' e 'send_on_check'",
            ValidateAppConfiguration.INVALID_LINK: "'link' non valido",
            ValidateAppConfiguration.INTERVAL_INVALID_FORMAT: "'interval' ha un formato errato",
            ValidateAppConfiguration.INTERVAL_MISSING_VALUES: "'interval' ha valori mancanti",
            ValidateAppConfiguration.INTERVAL_NON_POSITIVE_VALUES: "'interval' ha valori negativi",
            ValidateAppConfiguration.SEND_ON_CHECK_INVALID_TYPE: "'send_on_check' deve essere un booleano"
        }
        message = messages.get(code, 'Errore Sconosciuto')
        return ValidateResult('app', code, message)


class ValidatePermission(ValidateResult):
    SUCCESS = 0
    INVALID_TYPE = -4

    @staticmethod
    def get_outcome(code, field='default_permissions'):
        # noinspection PyShadowingNames
        messages = {
            ValidateSendOnCheckOutcome.SUCCESS: f"Valore '{field}' valido",
            ValidateSendOnCheckOutcome.INVALID_TYPE: f"'{field}' deve contenere valori booleani"
        }
        message = messages.get(code, 'Errore Sconosciuto')
        return ValidateResult(field, code, message)


class ConversationState(Enum):
    # MainMenu
    CHANGE_SETTINGS = 0
    MANAGE_APPS = 1
    UNSUSPEND_APP = 2
    MANAGE_APPS_OPTIONS = 3
    LIST_APPS = 4

    # AddApp
    SEND_LINK = 5
    SEND_LINK_FROM_EDIT = 6
    SEND_LINK_FROM_REMOVE = 7
    CONFIRM_APP_NAME = 8
    ADD_OR_EDIT_FINISH = 9

    # SetApp
    SET_INTERVAL = 10
    CONFIRM_INTERVAL = 11
    SEND_ON_CHECK = 12
    SET_UP_ENDED = 13

    # EditApp
    EDIT_SELECT_APP = 14
    EDIT_CONFIRM_APP = 15
    EDIT_NO_APPS = 16

    # DeleteApp
    DELETE_APP_SELECT = 17
    DELETE_APP_CONFIRM = 18

    # BackupRestore
    BACKUP_MENU = 19
    BACKUP_COMPLETED = 20
    BACKUP_SELECTED = 21
    BACKUP_DELETE = 22
    BACKUP_RESTORE = 23

    # User Managing
    USERS_MANAGING_MENU = 24
    ADD_USER = 25
    CONFIRM_USER = 26
    ADD_USER_LABEL = 27
    CONFIRM_LABEL = 28

    SET_PERMISSION = 29

    REMOVE_USER = 30
    CONFIRM_REMOVE_USER = 31

    TO_BE_ENDED = 100
