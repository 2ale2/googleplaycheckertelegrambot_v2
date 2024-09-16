import yaml
import datetime

serialization_registry = {}


def register_class(cls, serialize, deserialize):
    serialization_registry[cls.__name__] = {
        'serializer': serialize,
        'deserializer': deserialize
    }


def custom_serializer(obj):
    obj_type = type(obj).__name__

    if obj_type in serialization_registry:
        return {
            "__type__": obj_type,
            **serialization_registry[obj_type]["serializer"](obj)
        }
    raise TypeError(f"L'oggetto di tipo {obj_type} non è serializzabile."
                    f" Crea una funzione adeguata e aggiungila al registro.")


def custom_deserializer(dct):
    if "__type__" in dct:
        obj_type = dct["__type__"]
        if obj_type in serialization_registry:
            return serialization_registry[obj_type]["deserializer"](dct)
        raise TypeError(f"Non riesco a deserilizzare l'oggetto di tipo {obj_type}."
                        f" È Possibile che tu non abbia creato la funzione di "
                        f"deserializzazione oppure che tu non la abbia aggiunta al registro.")
    return dct


def serialize_timedelta(td):
    return {"days": td.days, "seconds": td.seconds}


def deserialize_timedelta(dct):
    return datetime.timedelta(**(dct.pop("__type__")))


register_class(datetime.timedelta, serialize_timedelta, deserialize_timedelta)


class CustomDumper(yaml.Dumper):
    def represent_data(self, data):
        try:
            return super().represent_data(custom_serializer(data))
        except TypeError:
            return super().represent_data(data)


class CustomLoader(yaml.Loader):
    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        return custom_deserializer(mapping)


def serialize_dict_to_yaml(data, filepath):
    with open(filepath, "w") as f:
        yaml.dump(data, f, default_flow_style=False, Dumper=CustomDumper)


def deserialize_dict_from_yaml(filepath):
    with open(filepath, "r") as f:
        return yaml.load(f, Loader=CustomLoader)
