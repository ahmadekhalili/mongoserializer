from rest_framework import serializers

from bson import ObjectId

import datetime
try:
    import jdatetime
except:
    pass


class TimestampField(serializers.Field):
    # 'jalali' means Solar date instead of Gregorian
    def __init__(self, jalali=False, auto_now=False, auto_now_add=False, *args, **kwargs):
        self.jalali = jalali
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        # when take value from like instance.updated or validated_data
        if not self.jalali and isinstance(value, datetime.datetime) or self.jalali and isinstance(value, jdatetime.datetime):
            return int(value.timestamp())  # value.timestamp() returns float
        else:                 # when take value from mongo db
            return value

    def get_value(self, dictionary):
        update_phase = getattr(self.parent, 'pk', False) or getattr(self.parent, 'instance', False)
        # in creation, both of fields with auto_now or auto_now_add have to add.
        if (self.auto_now_add or self.auto_now) and not update_phase:
            return True
        elif self.auto_now and update_phase:
            return True
        else:
            return super().get_value(dictionary)

    def to_internal_value(self, data):
        if self.auto_now_add or self.auto_now:
            if self.jalali:
                return jdatetime.datetime.now()
            return datetime.datetime.now()
        else:
            try:
                if self.jalali:
                    return jdatetime.datetime.fromtimestamp(int(data))
                return datetime.datetime.fromtimestamp(int(data))
            except ValueError:
                raise ValueError("you have to input in timestamp format, but provided: {{ data }}")


class DateTimeFieldMongo(serializers.DateTimeField):
    def __init__(self, auto_now=False, auto_now_add=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add

    def to_internal_value(self, data):
        def get_datetime():
            if self.jalali:
                jdatetime.datetime.now()
            else:
                datetime.datetime.now()

        update_phase = getattr(self.parent, 'pk', False) or getattr(self.parent, 'instance', False)
        if self.auto_now_add and not update_phase:
            return get_datetime()
        elif self.auto_now and update_phase:
            return get_datetime()
        else:
            return super().to_internal_value(data)


class IdMongoField(serializers.Field):
    def to_representation(self, value):
        return str(value)

    def to_internal_value(self, data):
        if type(data) == str:
            return ObjectId(data)
