from __future__ import annotations

import json
import pathlib


class WSDLType:
    TYPE = None

    def __init__(self):
        self.obj = self.TYPE()

    def __call__(self, *args, **kwargs):
        return self.obj


class ArrayOfUnsignedInt(WSDLType):

    def __init__(self):
        super().__init__()

    def assign(self, l: list):
        self.obj.unsignedInt = l

    def append(self, value):
        self.obj.unsignedInt.append(value)

    def __len__(self):
        return len(self.obj.unsignedInt)

    def __iter__(self):
        return self.obj.unsignedInt.__iter__()


class EventFilter(WSDLType):

    def __init__(self):
        super().__init__()
        self.TransactionTypes = ArrayOfUnsignedInt()

    def fromJson(self, event_path: str):
        if pathlib.Path(event_path).is_file():
            with open(event_path, "rb") as fin:
                try:
                    data = json.loads(fin.read().decode("utf-8"))
                    self.TransactionTypes.assign(data["transaction_types"])
                except Exception as e:
                    raise SyntaxError(str(e))
        else:
            raise FileNotFoundError

    def toWSDL(self):
        self.obj.TransactionTypes = self.TransactionTypes.obj
        return self.obj

    @staticmethod
    def initialize_type(session):
        EventFilter.TYPE = session.type("EventFilter")
        ArrayOfUnsignedInt.TYPE = session.type("ArrayOfUnsignedInt")