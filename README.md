# mongoserializer

mongoserializer is a Django helper package that introduces one of the best simple practices for interacting with MongoDB while using pymongo and Django REST Framework. This package is more of a programming paradigm than a tool.   

Whole workflow:   
![Imgur](https://i.imgur.com/m13ssNC.jpg)

## Installation

1. Run: ``` pip install mongoserializer[jalali]```  

To install mongoserializer with Jalali date support, add the ```[jalali]``` part.    

&nbsp;
## MongoSerializer

**MongoSerializer** is used only in the **writing** phase to write data in MongoDB, in a nice and clean format.
for **reading** phase you can [check here](#reading-phase). and conflicts using both of them [here](#read-write-conflicts-in-a-serializer).

### `MongoSerializer` arguments:

- **pk**:
  Used in updating. Assign the MongoDB document's `_id`  to update the document.

- **data**:
  data for create/update the document in the MongoDB.

- **request**:
  Optional. If your implementation requires 'request' (for validation, etc.), you can pass and use it like **self.request** inside your serializer.

- **partial**:
  Required to be True in updating.

### `MongoSerializer` methods:

- **is_valid(raise_exception=False)**:   
  Same as DRF is_valid(). returns boolean (True or False)

- **save(mongo_collection)**:   
  After `is_valid()`, pass `mongo_collection` (your MongoDB collection) to create/update the document.

- **serialize_and_filter(validated_data)**:   
  Convert `validated_data` to a serialized format ready to save in MongoDB. You can call **serialize_and_filter()** to directly save validated data to MongoDB.

**Example 1 (creation)**:
```python
from mongoserializer.serializer import MongoSerializer
from mongoserializer.fields import TimestampField
from mongoserializer.methods import ResponseMongo, MongoUniqueValidator

class BlogMongoSerializer(MongoSerializer):
    title = serializers.CharField(validators=[MongoUniqueValidator(mongo_db.blog, 'title')], max_length=255)
    slug = serializers.SlugField(required=False)  # Slug generates from title (in to_internal_value)
    published_date = TimestampField(auto_now_add=True, required=False)
    updated = TimestampField(auto_now=True, required=False)
    visible = serializers.BooleanField(default=True)
    author = UserNameSerializer(required=False)

    def to_internal_value(self, data):  # This method fills validated_data directly, after calling is_valid()
        if not data.get('slug') and data.get('title'):
            data['slug'] = slugify(data['title'], allow_unicode=True)
        internal_value = super().to_internal_value(data)

        if self.request:   # if you have pass request kwargs (like BlogMongoSerializer(..., request=reqeust))
            if self.request.user:
                internal_value['author'] = self.request.user
            else:
                raise ValidationError({'author': 'Please login to fill post.author'})
        elif data.get('author'):  # otherwise author's id should provide explicitly in request.data
            internal_value['author'] = get_object_or_404(User, id=data['author'])
        else:
            raise ValidationError({'author': "Please login and pass 'request' parameter or add user's id manually"})
        return internal_value

mongo_db = pymongo.MongoClient("mongodb://localhost:27017/")['my_db']
serializer = my_serializers.BlogMongoSerializer(data={"title": 'Hello', 'brief_description': 'about world'}, request=request)
if serializer.is_valid():
    data = serializer.save(mongo_db.blog)
    return ResponseMongo(data)
```

`validated_data` look like:
```python
{'title': 'Hello', 'slug': 'hello', 'published_date': datetime.datetime(2024, 5, 28, 9, 36, 54, 970462), 'updated': datetime.datetime(2024, 5, 28, 9, 36, 54, 970462), 'brief_description': 'about world', 'visible': True, 'author': <SimpleLazyObject: <User: user1>>}
```
while we only input **'title'** and **'brief_description'**, the following keys are additionally assigned to validated_data based on our setup:
- **'published_date'** (because of `auto_now_add` argument)
- **'updated'** (because of `auto_now` argument)
- **'slug'** (generates inside `to_internal_value` based on 'title')
- **'visible'** (default=True)
- **'user'** (assigned inside `to_internal_value`)

`data` returned from **.save()** is serialized version of `validated_data` and looks like:
```python
{"title": "Hello", "slug": "hello", "published_date": 1716878401, "updated": 1716878401, "brief_description": "about world", "visible": true, "author": {"id": 1, "url": "/users/profile/admin/1/", "user_name": "user1"}, "_id": ObjectId("66557c4188cc1acc1d1e0334")}
```
**Note**: `ResponseMongo` is similar to REST Framework's `Response`, but it converts any **ObjectId** to it's str, so it's required to use it instead of `Response`.

Full example in [below](#full-example-1)

&nbsp;  
**Example 2 (updating)**:  
```python
serializer = BlogMongoSerializer(pk='66557c4188cc1acc1d1e0334', data={"title": 'Hi'}, request=request, partial=True)
if serializer.is_valid():
    data = serializer.save(mongo_db.blog)
    return ResponseMongo(data)        # data == {"title": "Hi", "slug": "hi", "updated": 1716956932}
```
Now the mongo's document with **_id='66557c4188cc1acc1d1e0334'** updated. also '**updated**' field was updated too (because of `auto_now` argument).

&nbsp;  
**Example 3 (directly save to mongo)**:  
```python
serializer = BlogMongoSerializer(pk="66557c4188cc1acc1d1e0334", data={"author": {'id': 1}}, request=request, partial=True)
if serializer.is_valid():
    serialized = serializer.serialize_and_filter(serializer.validated_data)
    serialized['author']['user_name'] = serialized['author']['user_name'].replace('1', '_one')  # change 'user1' to 'user_one'
    mongo_db.blog.update_one({'_id': ObjectId("66557c4188cc1acc1d1e0334")}, {"$set": {'author.user_name': serialized['author']['user_name']}})
    return ResponseMongo(serialized)
```
Here we obtained final data ready to save, by `serialize_and_filter()` method. after that, the author's **user_name** is changed to 'user_one' and directly saved it to the document.


&nbsp;   
## Reading phase
Now after using `BlogMongoSerializer` for writing blogs in MongoDB, you can show it directly or via serializers.

### Directly:
```python
from bson import ObjectId

class PostDetail(views.APIView):
    def get(self, request, *args, **kwargs):
        post = blog_col.find_one({"_id": ObjectId(kwargs['pk'])})
        return ResponseMongo(post)
```

   
### Serializers:
For blog list you can create `BlogListSerializer` and for blog detail (page) `BlogDetailSerializer`.

```python
from mongoserializer.serializer import MongoSerializer
from mongoserializer.fields import TimestampField
from mongoserializer.methods import ResponseMongo, MongoUniqueValidator

class BlogListSerializer(MongoSerializer):
    title = serializers.CharField(validators=[MongoUniqueValidator(mongo_db.blog, 'title')], max_length=255)
    slug = serializers.SlugField(required=False)  # Slug generates from title (in to_internal_value)


class BlogDetailSerializer(MongoSerializer):
    title = serializers.CharField(validators=[MongoUniqueValidator(mongo_db.blog, 'title')], max_length=255)
    slug = serializers.SlugField(required=False)  # Slug generates from title (in to_internal_value)
    published_date = TimestampField(auto_now_add=True, required=False)
    updated = TimestampField(auto_now=True, required=False)
    ...
```

&nbsp;   
### Read Write conflicts in a serializer
If you use `MongoSerializer` class in read/write operations, as is conventional in DRF, you may face serious conflicts.   
suppose a `UserSerializer`, used to save user model in MongoDB and show it again:

![Imgur](https://i.imgur.com/yULeog1.jpg)
so reading phase needs some data that in writing phase may haven't been provided. specially for complex production
architectures that may contain several nested serializers in a serializer, this could be an actual problem. 

&nbsp;   
### Full example 1:  
```python
from django.utils.text import slugify
from django.shortcuts import get_object_or_404
from django.contrib.auth.models  import User
from rest_framework import serializers
from rest_framework import views
from rest_framework.exceptions import ValidationError

import pymongo
from mongoserializer.serializer import MongoSerializer
from mongoserializer.fields import TimestampField
from mongoserializer.methods import ResponseMongo, MongoUniqueValidator

mongo_db = pymongo.MongoClient("mongodb://localhost:27017/")['my_db']

class UserNameSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'url', 'user_name']

    def get_url(self, obj):
        return '/test/user/url/'

    def get_user_name(self, obj):
        return obj.username


class BlogMongoSerializer(MongoSerializer):
    title = serializers.CharField(validators=[MongoUniqueValidator(mongo_db.blog, 'title')], max_length=255)
    slug = serializers.SlugField(required=False)    # slug generates from title (in to_internal_value)
    published_date = TimestampField(auto_now_add=True, required=False)
    updated = TimestampField(jalali=True, required=False)
    visible = serializers.BooleanField(default=True)
    author = UserNameSerializer(required=False)

    def to_internal_value(self, data):  # this methods fills validated_data directly, after calling is_valid()
        if not data.get('slug') and data.get('title'):
            data['slug'] = slugify(data['title'], allow_unicode=True)  # data==request.data==self.initial_data mutable
        internal_value = super().to_internal_value(data)

        if self.request:
            if self.request.user:
                internal_value['author'] = self.request.user
            else:
                raise ValidationError({'author': 'please login to fill post.author'})
        elif data.get('author'):
            internal_value['author'] = get_object_or_404(User, id=data['author'])
        else:
            raise ValidationError({'author': "please login and pass 'request' parameter or add user id manually"})
        return internal_value


class HomePage(views.APIView):
    def post(self, request, *args, **kwargs):
        serializer = BlogMongoSerializer(data={"title": 'Hello', 'brief_description': 'about world'}, request=request)
        if serializer.is_valid():
            data = serializer.save(mongo_db.blog)
            return ResponseMongo(data)
        else:
            return ResponseMongo(serializer.errors)
```
