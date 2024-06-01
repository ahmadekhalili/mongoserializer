from django.utils.translation import activate, get_language

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.validators import UniqueValidator
import io
import json
from bson import ObjectId
from collections.abc import Iterable


def get_parsed_data(data):
    # data type is dict
    content = JSONRenderer().render(data)
    stream = io.BytesIO(content)
    return JSONParser().parse(stream)


def save_to_mongo(collection, pk=None, data=None):
    # 'pk' is pk of collection in mongo db used in updating, 'data' type is dict
    language_code = get_language()
    activate('en')
    if not pk:
        data = get_parsed_data(data)
        collection.insert_one(data)
    else:
        data = get_parsed_data(data)
        collection.update_one({'_id': ObjectId(pk)}, {"$set": data})
    activate(language_code)
    return data


# convert dict to object like: DictToObject({'spec': {'age': 22}}).spec.age==22, can also use list
class DictToObject:
    # 'data' can be dict or list of dicts (pass many=True)
    # if a serializer fields are 'a', 'b' and only 'a' provided in data, all_fields make b=None to prevent error
    def __init__(self, data, many=None, all_fields=None):
        self.items = None     # used in repr
        instance = CallBack(data=data)
        # we set self.sub_counter and self.data, to DictToObject (need in def repr, ...)
        for attr_name, attr_value in instance.__dict__.items():
            setattr(self, attr_name, attr_value)
        if isinstance(data, dict):   # data is dict
            if all_fields:
                # {'_id': None} will cause saving _id=None is db (in PostMongoSerializer)
                if all_fields.get('_id'):
                    del all_fields['_id']
                [setattr(instance, field, None) for field in all_fields if field not in data]
        # manage list and MongoDB cursor (col.find(....))
        elif isinstance(data, Iterable) and not isinstance(data, (str, bytes)):
            if not many:
                raise ValueError("class DictToObject: Iterable data type, pass 'many=True' to fix")
            if all_fields:
                for obj, dic in zip(instance, list(data)):
                    [setattr(obj, field, None) for field in all_fields if field not in dic]
            self.items = instance.items
        else:
            raise ValueError("Unsupported data type for conversion: must be dict or list of dicts")

    def __getitem__(self, key):
        if hasattr(self, "items"):
            return self.items[key]
        else:
            raise TypeError("Index access is not supported on this object")

    def __repr__(self):
        if self.sub_counter == 1:
            # in mongo cursor (.find()) self.data don't show actual data and needs to self.items
            data = self.items if self.items else self.data
            return f'Class {self.__class__.__name__}: ' + repr(data)
        return repr(self.data)


class CallBack:
    # sub_counter counts calls of CallBack like: CallBack(data) sub_counter==1 for use in __repr__
    def __init__(self, data, sub_counter=None):
        self.data = data
        self.sub_counter = 1 if not sub_counter else sub_counter
        if isinstance(data, dict):
            self.items = {}
            for key, value in data.items():
                # for keys like '240' now we can: obj['240'] and even obj['240'].image, instead obj.240 (error)
                if isinstance(key, int) or isinstance(key, str) and key.isdigit():
                    self.items[key] = self._convert(value)
                else:
                    setattr(self, key, self._convert(value))
        # manage list and MongoDB cursor (doc.find(....))
        elif isinstance(data, Iterable) and not isinstance(data, (str, bytes)):
            self.items = [self._convert(item) for item in data]

    def _convert(self, value):
        if isinstance(value, dict):
            return self.__class__(value, self.sub_counter + 1)
        elif isinstance(value, list):
            return [self._convert(item) for item in value]
        else:
            return value

    def __getitem__(self, key):
        if hasattr(self, "items"):
            return self.items[key]
        else:
            raise TypeError("Index access is not supported on this object")

    def __iter__(self):
        if self.items:
            return iter(self.items)

    def __repr__(self):
        if self.sub_counter == 1:
            return f'Class {self.__class__.__name__}: ' + repr(self.data)
        return repr(self.data)


class MongoUniqueValidator(UniqueValidator):
    def __init__(self, collection, field, message=None):
        self.queryset = None      # provide value None for default attribute
        self.collection = collection
        self.field = field
        self.message = message or f'The {field} must be unique.'

    def __call__(self, value, serializer_field):
        self.pk = getattr(serializer_field.parent, 'pk', None)
        query = {self.field: value}
        if self.pk:
            # in updating, search all collections (for validating unique) except current collection
            query['_id'] = {'$ne': ObjectId(self.pk)}
        if self.collection.find_one(query):
            raise serializers.ValidationError(self.message)


class ObjectIdJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)


class ResponseMongo(Response):    # ResponseMongo(data), convert all nested ObjectId('...') of 'data' to serialized str
    def __init__(self, data=None, status=None, template_name=None, headers=None, content_type=None):
        if data is not None:
            # Convert the data to JSON using the custom encoder
            data = json.loads(json.dumps(data, cls=ObjectIdJSONEncoder))
        super().__init__(data=data, status=status, template_name=template_name, headers=headers, content_type=content_type)
