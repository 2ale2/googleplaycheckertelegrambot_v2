import yaml
import datetime
import logging
from logging import handlers

br_logger = logging.getLogger('br_logger')
br_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = handlers.RotatingFileHandler(filename="logs/formatter.log",
                                            maxBytes=1024, backupCount=1)
file_handler.setFormatter(formatter)
br_logger.addHandler(file_handler)


class CustomDumper(yaml.Dumper):
    def represent_data(self, data):
        return super().represent_data(data)


class CustomLoader(yaml.Loader):
    def construct_mapping(self, node, deep=False):
        return super().construct_mapping(node, deep=deep)


def timedelta_representer(dumper, value):
    return dumper.represent_mapping('!timedelta', {
        'days': value.days,
        'seconds': value.seconds
    })


def timedelta_constructor(loader, node):
    value = loader.construct_mapping(node, deep=True)
    return datetime.timedelta(**value)


yaml.add_representer(datetime.timedelta, timedelta_representer)
yaml.add_constructor('!timedelta', timedelta_constructor)


def serialize_dict_to_yaml(data, filepath) -> bool:
    with open(filepath, 'w') as f:
        try:
            yaml.dump(data, f, default_flow_style=False, Dumper=CustomDumper)
        except yaml.YAMLError as exc:
            br_logger.error(f'Errore durante il dumping: {exc}')
            return False
        return True


def deserialize_dict_from_yaml(filepath):
    with open(filepath, "r") as f:
        try:
            return yaml.load(f, Loader=CustomLoader)
        except yaml.YAMLError as exc:
            br_logger.error(f"Errore nel caricamento delle informazioni: {exc}")
            return None
