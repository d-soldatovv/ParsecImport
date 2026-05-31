import json
import pathlib
import zeep


class ConnectionConfig:
    def __init__(self, config_path: str):
        if pathlib.Path(config_path).is_file():
            with open(config_path, "rb") as fin:
                data = json.loads(fin.read().decode("utf-8"))
                try:
                    self.host_addr = data["host_addr"]
                    self.organization = data["organization"]
                    self.username = data["username"]
                    self.password = data["password"]
                    self.integrational_service_url_path_template = data["integrational_service_url_path_template"]
                except KeyError as e:
                    raise SyntaxError(
                        "Incorrect connection config\n"
                        "missing obligatory params:[host_addr, organization, username, password, integrational_service_url_path_template]\n"
                        f"{str(e)}"
                    )
        else:
            raise FileNotFoundError(config_path)


class IntegrationalServiceSession:
    def __init__(self, config: ConnectionConfig):
        self.url = config.integrational_service_url_path_template.format(config.host_addr)
        self.client = zeep.Client(self.url)

        for func_name, func in self.client.service.__dict__["_operations"].items():
            self.__setattr__(func_name, func)

        if hasattr(self, "OpenSession"):
            self.session = self.OpenSession(config.organization, config.username, config.password)
            if self.session.Result == -1:
                raise ConnectionError(self.session.ErrorMessage)
            self.session = self.session.Value
            self.sessionId = self.session.SessionID
        else:
            raise KeyError(f"Method OpenSession wasn't found at {self.url}")

    def __del__(self):
        if hasattr(self, "CloseSession") and hasattr(self, "sessionId"):
            try:
                self.CloseSession(self.sessionId)
            except Exception:
                pass

    def __resolve_namespace(self):
        for key, value in self.client.namespaces.items():
            if "Parsec3IntergationService" in value:
                self.parsec_namespace = key

    def type(self, type_name: str, namespace: str = None):
        if not hasattr(self, "parsec_namespace"):
            self.__resolve_namespace()
        try:
            if namespace:
                return self.client.get_type(f"{namespace}:{type_name}")
            return self.client.get_type(f"{self.parsec_namespace}:{type_name}")
        except Exception:
            return None