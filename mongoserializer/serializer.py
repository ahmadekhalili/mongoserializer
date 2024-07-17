from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .methods import save_to_mongo, DictToObject


class MongoSerializer(serializers.Serializer):

    def __init__(self, instance=None, pk=None, request=None, *args, **kwargs):
        # instance and pk should not conflict in updating and retrieving like: updating: serializer(pk=1, data={..}),
        # retrieving: serializer(instance).data
        self.pk = pk
        self.request = request
        super().__init__(instance=instance, *args, **kwargs)
        self.context.update({'request': self.request})

    def to_representation(self, instance):
        if self.partial:      # in updating only provided fields should validate
            for key in self.fields:
                self.fields[key].required = False

        representation = super().to_representation(instance)
        rep2 = representation.copy()
        if self.partial:
            for key in rep2:    # can't change dictionary (representation) during iteration
                if representation.get(key) is None:
                    representation.pop(key)
        return representation

    def save(self, mongo_collection, **kwargs):
        if not self.pk:   # creation phase
            return self.create(mongo_collection)
        else:             # updating
            return self.update(self.pk, mongo_collection)

    def create(self, mongo_collection):
        serialized = self.serialize_and_filter(self.validated_data)
        return save_to_mongo(collection=mongo_collection, data=serialized)

    def update(self, pk, mongo_collection):
        # because partial=True don't raise error when 'validated_data' doesn't provide required fields
        serialized = self.serialize_and_filter(self.validated_data)
        return save_to_mongo(mongo_collection, pk, data=serialized)

    def serialize_and_filter(self, validated_data):
        # serialize and next, keep only fields provided in request.data and remove unexpected others
        serialized = self.get_serialized(validated_data)
        if self.partial:
            serialized = self._field_filtering_for_update(validated_data, serialized)
        return serialized

    def get_serialized(self, validated_data):
        # when partial=True, current_class(validated_data) doesn't raise error even doesn't provide required fields
        current_class = self.__class__
        serialized = current_class(DictToObject(validated_data), partial=self.partial).data
        return serialized

    def _field_filtering_for_update(self, validated_data, serialized):
        # keep only fields provided in validated_data and remove unexpected others (fields with defaut value,
        # None value or ...). we prevent override unexpected keys in db.
        for key in serialized.copy():
            if key not in validated_data:
                del serialized[key]
        return serialized
