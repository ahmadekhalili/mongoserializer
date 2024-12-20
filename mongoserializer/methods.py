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
from pymongo import UpdateOne


def call_back_serializer_id(data):
    if isinstance(data, dict):
        for key in data:
            if isinstance(data[key], dict):
                call_back_serializer_id(data[key])
            elif isinstance(data[key], list):
                call_back_serializer_id(data[key])
            else:
                if key == '_id':
                    data[key] = str(data[key])
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                call_back_serializer_id(item)
            elif isinstance(item, list):
                call_back_serializer_id(item)
    return data


def call_back_deserializer_id(data):
    if isinstance(data, dict):
        for key in data:
            if isinstance(data[key], dict):
                call_back_deserializer_id(data[key])
            elif isinstance(data[key], list):
                call_back_deserializer_id(data[key])
            else:
                if key == '_id':
                    data[key] = ObjectId(data[key])
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                call_back_deserializer_id(item)
            elif isinstance(item, list):
                call_back_deserializer_id(item)
    return data


def get_parsed_data(data):  # will be depracated
    # data type is dict
    data = call_back_serializer_id(data)
    content = JSONRenderer().render(data)
    stream = io.BytesIO(content)
    parsed = JSONParser().parse(stream)
    parsed = call_back_deserializer_id(parsed)
    return parsed


def get_mongo_get_query(serializer):  # for query like: "comments.$.author.profile.", put related idof each field like:
    # {'comments.$.': _id1, 'comments.$.author.': _id6, ...}
    serializer_query = serializer.query.replace('.$', '')
    dot_counter, parent = -1, serializer
    queries = {f'{serializer_query}_id': serializer._id}
    for i in range(1, len(serializer_query)):
        if serializer_query[i] == '.':
            dot_counter += 1
            if serializer_query[i-1] == '$':
                dot_counter -= 1
        if dot_counter == 1:
            parent = parent.parent
            queries[f'{serializer_query[:i + 1]}_id'] = parent._id


def save_to_mongo(serializer, _id=None, id=None, data=None, root_id=None):
    # '_id' is id of serializer, could be main serializer's id or nested serializer's id
    # 'root_id' is id of main serializer, is None when serializer==main serializer, only available for nested serializer
    # push for ArrayFields should be done manually, push in two level nested (blog.profiles.comments) not supported

    collection, query = serializer.mongo_collection, serializer.query
    language_code = get_language()
    activate('en')
    if isinstance(data, dict):
        if not root_id:
            if not _id and not id:   # creation phase
                collection.insert_one(data)
            elif id and _id:  # update django field (only main fields not nested)
                collection.update_one({"_id": ObjectId(_id)}, {"$set": {query[0][:-1]: data}})
            elif _id:      # update main document, non nested documents. if root_id == _id, root_id is None
                query_set = {f'{query[0]}{attr}': value for attr, value in data.items()}
                collection.update_one({'_id': ObjectId(_id)}, {"$set": query_set})

        else:      # update nested documents
            # _id could be created by IdMongoField, so its not good identifier instead 'add'
            if query[1] == 'add_array':    # append to the nested array field (like to blog1.comments)
                query_push = query[0][:-3] if query[0][-2] == '$' else query[0][:-1]
                collection.update_one({'_id': ObjectId(root_id)}, {"$push": {query_push: data}})
            elif query[1] == 'add_dict':    # add to the blank nested dict field or reset (like to blog1.profile)
                query_set = {f'{query[0]}{attr}': value for attr, value in data.items()}
                collection.update_one({'_id': ObjectId(root_id)}, {"$set": query_set})
            elif query[1] == 'edit':          # edit the nested document
                query_set = {f'{query[0]}{attr}': value for attr, value in data.items()}
                get_query = query[0].replace('.$', '')
                if _id:
                    collection.update_one({'_id': ObjectId(root_id), f"{get_query}_id": ObjectId(_id)}, {"$set": query_set})
                else:  # just to be safe
                    collection.update_one({'_id': ObjectId(root_id)}, {"$set": query_set})
        activate(language_code)

    elif isinstance(data, list):
        if id:          # django fields level 1. if document not exists in db push, otherwise refresh
            updates = []
            for i, item in zip(id, data):
                get_query = query[0].replace('.$', '')
                query_set = {f'{query[0]}{attr}': value for attr, value in item.items()}
                updates.append(UpdateOne(
                    {"_id": ObjectId(_id), f"{get_query}id": i}, {"$set": {query[0][:-1]: dict(item)}},
                    upsert=False)
                )
                updates.append(UpdateOne(
                    {"_id": ObjectId(_id), f"{get_query}id": {'$ne': i}}, {"$push": {query[0][:-3]: dict(item)}},
                    upsert=False)
                )
            if updates:
                collection.bulk_write(updates)

        elif not _id:
            collection.insert_many(data)
        else:
            raise ValueError('update not implemented')
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
        self._id = getattr(serializer_field.parent, '_id', None)
        query = {self.field: value}
        if self._id:
            # in updating, search all collections (for validating unique) except current collection
            query['_id'] = {'$ne': ObjectId(self._id)}
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
