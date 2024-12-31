import rest_framework.fields
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404

from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework.exceptions import ValidationError
from rest_framework.fields import get_error_detail, set_value, SkipField

from collections import OrderedDict
from copy import deepcopy

from .methods import save_to_mongo
from .fields import IdMongoField


def to_internal_value_model(self, data):  # for ModelSerializer, fill self .validated_data
    return get_object_or_404(self.Meta.model, id=data)


def to_internal_value_model_many(self, data):  # for ModelSerializer when many=True
    return self.child.Meta.model.objects.filter(id__in=data)


class MongoListSerializer(serializers.ListSerializer):

    def __init__(self, instance=None, _id=None, id=None, **kwargs):
        # instance, _id, data... are list, id for django fields, should provide explecitly
        self._id = _id
        self.id = id
        self.root_id = _id if _id else None
        self._context = kwargs.get('context', {})
        self.query = ['', 'edit']   # add/edit
        self.mongo = False if id or isinstance(self.child, serializers.ModelSerializer) else True  # is mongo|django field?
        super().__init__(instance=instance, **kwargs)
        try:
            # if the serializer not define Meta (for example in nested fields), 'except' will be run
            self.mongo_collection = self.child.Meta.model
        except:
            self.mongo_collection = None       # mongo_collection of nested fields sets in .to_internal_value()
        if not self._context:   # self._context converted to None by base classes and cause raising error when setting
            self._context = {}
        # for integrity with 'root_id' and ..., we dont set mongo_collection for ListSerializer (all set in .child)
        self.context.update({'partial': self.partial, 'change': bool(_id or id)})

    def to_internal_value(self, data):
        # parent of list fields is main serializer like 'BlogSerializer'
        if not isinstance(data, list):
            raise ValidationError(f'please provide `list` data type for `{self.__class__.__name__}`')
        if getattr(self, 'parent', None) and getattr(self.parent, 'request', None):
            self.child.mongo_collection = self.mongo_collection = self.parent.mongo_collection
            self.context.update({'request': self.parent.request, 'partial': self.parent.partial,
                                 'change': bool(self._id or self.id)})

        if self._id or self.root_id:  # self.root_id for update nested documents and self._id for update main document
            ret = []
            self.child.root_id = self.root_id
            self.child.partial = True
            self.child.mongo_collection = self.mongo_collection
            self._id = [None for item in data] if not self._id else self._id
            for id, dct in zip(self._id, data):
                # _id shared to Serializer and ListSerializer just same (as list), so should be separated here
                self.child._id = id
                ret.append(self.child.to_internal_value(dct))
        else:
            ret = [self.child.to_internal_value(dct) for dct in data]
        return ret

    def save(self):
        list_of_serialized = [self.child.get_serialized(dct) for dct in self.validated_data]
        if not self._id:   # creation phase
            return self.create(list_of_serialized)
        else:             # updating
            return self.update(self._id, list_of_serialized)

    def create(self, validated_data):
        return save_to_mongo(self, data=validated_data)

    def update(self, _id=None, validated_data=None):  # provide validated_data (adding like blog.user.set(user2) or both (editing)
        # if you prefere update via own field, don't call super().update
        if validated_data is None:
            validated_data = _id
            _id = None
        if not _id:        # for django fields
            _id = [None for dct in validated_data]

        if self.parent is None and isinstance(self.root_id, list):   # self is main serializer not nested
            list_of_serialized = []
            for id, dct in zip(_id, validated_data):
                self.child.root_id = id
                list_of_serialized.append(self.child.update(id, dct))
        else:
            list_of_serialized = [self.child.update(id, dct) for id, dct in zip(_id, validated_data)]
        return list_of_serialized

    def serialize_and_filter(self, validated_data):
        # serialize and next, keep only fields provided in request.data and remove unexpected others
        serialized = self.get_serialized(validated_data)
        if self.partial:
            serialized = self._field_filtering_for_update(validated_data, serialized)
        return serialized

    def get_serialized(self, validated_data):
        # when partial=True, current_class(validated_data) doesn't raise error even doesn't provide required fields
        current_class = self.__class__
        serialized = current_class(validated_data, partial=self.partial).data
        return serialized

    def _field_filtering_for_update(self, validated_data, serialized):
        # Keep only fields provided in validated_data and remove unexpected others (fields with default value,
        # None value, or ...). Prevent override of unexpected keys in db.
        if isinstance(validated_data, dict):
            filtered_serialized = {key: value for key, value in serialized.items() if key in validated_data}
        else:
            filtered_serialized = {key: value for key, value in serialized.items() if getattr(validated_data, key)}
        return filtered_serialized


class FieldMixin(serializers.Serializer):
    # in nested fields '_id' field needed. like data={'title': '..', 'comments': {'_id':'..', ..}}
    _id = IdMongoField(required=False, mongo_write=True)  # generate ObjId for main and nested serializers in creation
    #root_id = IdMongoField(required=False, mongo_write=True)

class MongoSerializer(FieldMixin, serializers.Serializer):

    class Meta:
        list_serializer_class = MongoListSerializer

    def __init__(self, instance=None, _id=None, request=None, id=None, **kwargs):
        # instance and _id should not conflict in updating and retrieving like: updating: serializer(_id=1, data={..}),
        # retrieving: serializer(instance).data, id is for django fields
        self._id = _id
        self.root_id = _id if _id else None
        self.request = request
        self.query = ['', 'edit']   # add/edit
        self.id = id
        self.mongo = False if id or isinstance(self, serializers.ModelSerializer) else True  # is mongo|django field
        super().__init__(instance=instance, **kwargs)
        try:
            # if the serializer not define Meta (for example in nested fields), 'except' will be run
            self.mongo_collection = self.Meta.model
        except:
            self.mongo_collection = None       # mongo_collection of nested fields sets in .to_internal_value()
        self.fields_items = self.fields.items()  # used in MongoListSerializer to improve optimization (to_internal)
        for field_name, field in self.fields_items:
            if isinstance(field, serializers.BaseSerializer):  # for django fields required set field.query
                field.query = ['', 'edit']
                if not getattr(field, 'mongo', False):  # django fields
                    if getattr(field, 'many', False):  # list field
                        field.to_internal_value = to_internal_value_model_many.__get__(field)
                    else:
                        field.to_internal_value = to_internal_value_model.__get__(field)
        self.context.update({'request': request, 'partial': self.partial, 'change': bool(_id)})

    def _unrequired_nested_fields(self, serializer):
        if isinstance(serializer, serializers.BaseSerializer):
            if hasattr(serializer, 'many') and serializer.many:
                for field_name, field in serializer.child.fields.items():
                    field.required = False
                    self._unrequired_nested_fields(field)

            else:
                for field_name, field in serializer.fields.items():
                    field.required = False
                    self._unrequired_nested_fields(field)

    def to_representation(self, instance):
        if isinstance(instance, dict):
            ret = {}
            for field_name, field in self.fields.items():
                if self.partial:       # fields reset when came to to_representation, so required setting again
                    field.required = False
                    if isinstance(field, serializers.BaseSerializer):
                        field.partial = True  # for nested fields, required setting partial = True
                        if hasattr(field, 'many') and field.many:
                            field.child.partial = True  # field's child came here from ListSerializer.to_representation
                    self._unrequired_nested_fields(serializer=field)

                try:
                    value = instance[field_name]
                    if isinstance(field, serializers.SerializerMethodField):
                        method = getattr(self, f'get_{field_name}')
                        if method(instance):     # prevent 'None' value came to db in SerializerMethodField fields
                            ret[field_name] = method(instance)
                    elif isinstance(field, serializers.BaseSerializer):   # field is a nested serializer
                        field.instance = value
                        ret[field_name] = field.data
                    else:                      # field is normal field like CharField, ...
                        ret[field_name] = field.to_representation(value)
                except KeyError:
                    if field.default is not empty:         # field.default == '' | 0 | None | some_value
                        ret[field_name] = field.default
                    # if only one of 'allow_blank', 'allow_null' be False or required=True will not raise 'required' error
                    elif getattr(field, 'allow_blank', False) or getattr(field, 'allow_null', False) or not getattr(field, 'required', True):
                        continue
                    else:
                        raise ValidationError(f"'{field_name}' is required")
                except:        # python default message
                    raise
        else:      # class bases instance
            ret = super().to_representation(instance)
        if self.partial:         # filter here to apply filtering to the serializer fields too
            ret = self._field_filtering_for_update(instance, ret)
        return ret

    def validate_empty_values_django(self, data):
        """
        almost same with 'validate_empty_values' but limit validations for django fields (skip fields when do data
        provided and prevent from error
        """
        if self.read_only:
            return (True, self.get_default())

        if data is empty:
            raise SkipField()

        if data is None:
            if not self.allow_null:
                self.fail('null')
            # Nullable `source='*'` fields should not be skipped when its named
            # field is given a null value. This is because `source='*'` means
            # the field is passed the entire object, which is not null.
            elif self.source == '*':
                return (False, None)
            return (True, None)

        return (False, data)

    def _super_internal_value(self, data):
        # ListSerializer calls: child.run_validation -> child.to_internal_value
        ret = OrderedDict()
        errors = OrderedDict()
        fields = self._writable_fields

        for field in fields:
            validate_method = getattr(self, 'validate_' + field.field_name, None)
            primitive_value = field.get_value(data)
            try:
                if isinstance(field, serializers.BaseSerializer) and not getattr(field, 'mongo', False):
                    # for django fields don't validate (raise error)
                    (is_empty_value, data) = self.validate_empty_values_django(primitive_value)
                    if is_empty_value:
                        validated_value = data    # just like default DRF implementation, otherwise could raise error
                    validated_value = field.to_internal_value(primitive_value)
                else:
                    validated_value = field.run_validation(primitive_value)

                if validate_method is not None:
                    validated_value = validate_method(validated_value)
            except ValidationError as exc:
                errors[field.field_name] = exc.detail
            except DjangoValidationError as exc:
                errors[field.field_name] = get_error_detail(exc)
            except SkipField:
                pass
            else:
                set_value(ret, field.source_attrs, validated_value)
        if errors:
            raise ValidationError(errors)
        return ret

    def to_internal_value(self, data):   # data must be dict (not list)
        if self._id or self.root_id:  # self.root_id for update nested documents and self._id for update main document
            for field_name, field in self.fields.items():
                value = data.get(field_name)
                self._unrequired_nested_fields(field)
                if isinstance(field, serializers.BaseSerializer) and data.get(field_name):
                    if (isinstance(value, list) and not getattr(field, 'many', False)) or (isinstance(value, dict) and getattr(field, 'many', False)):
                        raise ValidationError(f'please provide right data type based on `many` argument for `{field_name}`')
                    field.partial = True  # being in update (_id==True equal to partial true)
                    field.mongo_collection = self.mongo_collection
                    field.root_id = self.root_id
                    if getattr(field, 'many', False):  # list field
                        if not getattr(field, 'mongo', False):  # django serializer, value is like: [1, 3, 5]
                            field.query = field.child.query = ['', 'add_array']  # add dict to the nested array db field
                        elif not value[0].get('_id'):
                            # we have to distinguish _id added via IdMongo and _id put by user
                            field.query[1] = field.child.query[1] = 'add_array'  # add dict to the nested array db field
                        else:   # value[0].get('_id')
                            field.query[1] = field.child.query[1] = 'edit'
                            field._id = [dct['_id'] for dct in value]
                        field.to_internal_value(value)  # convert to dict and return (via child.to_internal_value)

                    else:        # single (dict) field
                        if not getattr(field, 'mongo', False):  # django serializer
                            field.query = ['', 'add_dict']  # add the dict dada to the nested dict field in db
                        elif not value.get('_id'):
                            field.query[1] = 'add_dict'
                        else:  # value.get('_id'):
                            field.query[1] = 'edit'
                            field._id = value.get('_id')
        #return super().to_internal_value(data=data)
        return self._super_internal_value(data)   # super() could override field attributes

    def save(self, **kwargs):
        # serialization must be done here rather that create and update, because multiply calling
        # get_serialized(..) (by main serializer and its nested fields), raise error
        serialized = self.get_serialized(self.validated_data)
        serialized = {**serialized, **kwargs}
        if not self._id:   # creation phase
            return self.create(serialized, **kwargs)
        else:             # updating
            return self.update(self._id, serialized, **kwargs)

    def create(self, validated_data):
        return save_to_mongo(serializer=self, data=validated_data)

    def update(self, _id=None, validated_data=None):  # provide validated_data (adding) or both (editing)
        if validated_data is None:
            validated_data = _id
            _id = None
        # because partial=True don't raise error when 'validated_data' doesn't provide required fields
        return_serialized = deepcopy(validated_data)
        for field_name, field in self.fields_items:
            # field value could be None or 0
            if isinstance(field, serializers.BaseSerializer) and validated_data.get(field_name):  # nested Serializer
                # every serializer field should define its own .update to update
                value = validated_data.get(field_name)
                if getattr(field, 'mongo', False):
                    field.mongo_collection = self.mongo_collection  # fields attrs reset in to_internal_value so set again
                    field.root_id = self.root_id
                    if getattr(field, 'many', False):     # list value
                        field.child.mongo_collection = self.mongo_collection  # fields attrs reset in to_internal_value so set again
                        field.child.root_id = self.root_id
                        if value[0].get('_id'):  # edit document of the serializer's field
                            if field.query[1] == 'add_array':
                                keys = [dic['_id'] for dic in value if dic.get('_id')]  # _id created by IdMongoField
                            else:
                                keys = [dic.pop('_id') for dic in value if dic.get('_id')]
                        else:       # add document to the serializer field (only one level nested)
                            keys = None
                        field.query[0] = field.child.query[0] = f'{field.parent.query[0]}{field_name}.$.' if field.parent.query[0] else f'{field_name}.$.'  # .$. is required here, for next queries
                        field.update(keys, value)
                    else:      # dict value
                        if value.get('_id'):
                            if field.query[1] == 'add_dict':
                                _id = value['_id']  # _id created by IdMongoField
                            else:
                                _id = value.pop('_id')
                        else:       # add document to the serializer field (only one level nested)
                            _id = None
                        field.query[0] = f'{field.parent.query[0]}{field_name}.' if field.parent.query[0] else f'{field_name}.'
                        field.update(_id, value)

                else:        # django serializer field (update or refresh values)
                    if getattr(field, 'many', False):
                        field.mongo_collection = field.child.mongo_collection = self.mongo_collection
                        field.query[0] = field.child.query[0] = f'{field.parent.query[0]}{field_name}.$.' if field.parent.query[0] else f'{field_name}.$.'  # .$. is required here, for next queries
                        id = [item['id'] for item in value]
                    else:
                        field.mongo_collection = self.mongo_collection
                        field.query[0] = f'{field.parent.query[0]}{field_name}.' if field.parent.query[0] else f'{field_name}.'
                        id = value['id']
                    save_to_mongo(field, id=id, data=value, root_id=self.root_id)
                del validated_data[field_name]
        if validated_data:
            root_id = None if self.root_id == _id else self.root_id
            save_to_mongo(self, _id, data=validated_data, root_id=root_id)
        return return_serialized

    def serialize_and_filter(self, validated_data):
        # serialize and next, keep only fields provided in request.data and remove unexpected others
        serialized = self.get_serialized(validated_data)
        if self.partial:
            serialized = self._field_filtering_for_update(validated_data, serialized)
        return serialized

    def get_serialized(self, validated_data):
        # when partial=True, current_class(validated_data) doesn't raise error even doesn't provide required fields
        current_class = self.__class__
        serialized = current_class(validated_data, partial=self.partial).data
        return serialized

    def _field_filtering_for_update(self, validated_data, serialized):
        # Keep only fields provided in validated_data and remove unexpected others (fields with default value,
        # None value, or ...). Prevent override of unexpected keys in db.
        if isinstance(validated_data, dict):
            filtered_serialized = {key: value for key, value in serialized.items() if key in validated_data}
        else:
            filtered_serialized = {key: value for key, value in serialized.items() if getattr(validated_data, key)}
        return filtered_serialized

    @classmethod
    def many_init(cls, *args, **kwargs):
        """
        ListSerializer created here (when pass many=True in the serializer)
        """
        list_serializer_class = cls.Meta.list_serializer_class or MongoListSerializer
        if issubclass(list_serializer_class, MongoListSerializer):  # return True if is MongoListSerializer or subclass
            # custom operation for 'MongoListSerializer'
            kwargs['child'] = cls(*args, **kwargs)

            # add all arguments of ListSerializer manually (without args, kwargs), because passing custom arguments of
            # child serializer (like a=2) to ListSerializer could raise error (unless you define that argument
            # in ListSerializer)
            if args:
                instance = args[0]
            else:
                instance = kwargs.get('instance')
            _id, id = kwargs.get('_id'), kwargs.get('id')
            child, allow_empty, max_length, min_length = kwargs['child'], kwargs.get('allow_empty'), kwargs.get('max_length'), kwargs.get('min_length')
            data, partial = kwargs.get('data', empty), kwargs.get('partial')
            context, many = kwargs.get('context'), kwargs.get('many')
            return list_serializer_class(instance, _id=_id, id=id,
                                         child=child, allow_empty=allow_empty, max_length=max_length, min_length=min_length,
                                         data=data, partial=partial, context=context, many=many,
                                         read_only=kwargs.get('read_only', False), write_only=kwargs.get('write_only', False), required=kwargs.get('required', None), default=kwargs.get('default', empty), initial=kwargs.get('initial', empty), source=kwargs.get('source'), label=kwargs.get('label'), help_text=kwargs.get('help_text'), style=kwargs.get('style'), error_messages=kwargs.get('error_messages'), validators=kwargs.get('validators'), allow_null=kwargs.get('allow_null', False))

        else:    # don't add '_id=_id' argument or other custom operation for 'ListSerializer'
            return super().many_init(*args, **kwargs)
