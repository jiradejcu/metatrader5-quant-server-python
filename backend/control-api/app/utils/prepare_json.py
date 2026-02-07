import json

def prepare_json(json_str, default_value):
    if json_str == None:
            return default_value
    return json.loads(json_str)