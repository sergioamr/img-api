import os
import time
import shutil
import datetime

from mongoengine import *
from api.print_helper import *
from api.query_helper import *

from flask import current_app, abort
from flask_login import UserMixin, current_user

from imgapi_launcher import db, login_manager
from api.query_helper import mongo_to_dict_helper

from .signature_serializer import TimedJSONWebSignatureSerializer as Serializer, BadSignature, SignatureExpired


class DB_ItemMedia(db.DynamicEmbeddedDocument):
    media_id = db.StringField()
    update_date = db.DateTimeField()


class DB_MediaList(db.Document):
    """ A media list is a collection of items that an user likes, dislikes, or are a in a playlist """
    is_public = db.BooleanField(default=False)
    username = db.StringField()
    list_type = db.StringField()

    name = db.StringField()
    description = db.StringField()
    media_list = db.EmbeddedDocumentListField(DB_ItemMedia, default=[])

    def find_on_list(self, media_id):
        for idx, item in enumerate(self.media_list):
            if item.media_id == media_id:
                return idx

        return -1

    def is_on_list(self, media_id):
        return self.find_on_list(media_id) != -1

    def convert_to_dict(self):
        ret = {}
        for item in self.media_list:
            ret[item.media_id] = item.update_date

        return ret

    def add_to_list(self, media_id):
        """ Adds to a list if it doesn't have the media """

        if self.find_on_list(media_id) != -1:
            print_r(" Duplicated ")
            return False

        item = DB_ItemMedia(**{"media_id": media_id, "update_date": datetime.datetime.now()})

        self.media_list.append(item)
        self.save()
        return True

    def remove_from_list(self, media_id):
        """ Remove from a list of media """

        res = self.find_on_list(media_id)
        if res == -1:
            return False

        self.media_list.pop(res)
        self.save()
        return True

    def check_permissions(self):
        if not self.is_public and self.username != current_user.username:
            return abort(401, "Unauthorized")

        return True


class DB_UserInteractions(db.DynamicEmbeddedDocument):
    """ User interaction is every item that the user wants to store as a collection
        User stores media lists, which are just lists of IDs and media with special information.

        They might be building a list of favourite wedding dresses, or whatever.

        We have our default media collections which are Favourites "favs", likes and dislikes.
        The rest of collections are dynamic.

        Users should have a limit in the amount of collections they can create.
    """

    def get_media_list(self, list_id):
        return DB_MediaList.objects(pk=list_id).first()

    def get_dict(self, list_id):
        res = self.get_media(list_id)
        if not res: return {}
        return res.convert_to_dict()

    def serialize(self):
        """ Return the media in dictionaries for quick frontend access """

        ret = {
            'likes': self.get_dict(self.list_likes),
            'dislikes': self.get_dict(self.list_dislikes),
            'favs': self.get_dict(self.list_favs),
        }

    def is_on_list(self, media_id, media_list_name):
        if not media_id or not media_list_name:
            return False

        if media_list_name not in self:
            return False

        media_list = self.get_media_list(self[media_list_name])
        if not media_list:
            return False

        return media_list.is_on_list(media_id)

    def populate(self, media_list):
        """ Adds if the user liked or disliked the media """

        for media in media_list:
            m_id = media['media_id']

            if m_id == "627290d4823ab1885436e9b7":
                print(" Test ")

            if self.is_on_list(m_id, 'list_favs_id'):
                media['favs'] = True

            if self.is_on_list(m_id, 'list_likes_id'):
                media['like'] = True

            if self.is_on_list(m_id, 'list_dislikes_id'):
                media['dislike'] = True

    def perform(self, media_id, action, media_list_short_name):
        """ Executes an action on the user's media lists
            Current available actions are:
                - Append a media
                - Remove a media
        """

        if action in ['append', 'remove', 'toggle']:
            name_id = "list_" + media_list_short_name + "_id"

            if (name_id in self or hasattr(self, name_id)) and self[name_id]:
                media_list = self.get_media_list(self[name_id])
            else:
                media_list = DB_MediaList(**{"username": current_user.username, "list_type": media_list_short_name})
                media_list.save().reload()
                self[name_id] = str(media_list.id)

            if action == "toggle":
                if media_list.is_on_list(media_id):
                    action = "remove"
                else:
                    action = "append"

            if action == "append":
                media_list.add_to_list(media_id)
            elif action == "remove":
                media_list.remove_from_list(media_id)

            return True, {'action': 'success', 'media_list_id': str(media_list.id)}

    def get_list_id(self, name_or_id):
        if len(name_or_id) != 24:
            if not name_or_id.startswith("list_"):
                name_or_id = "list_" + name_or_id + "_id"

            if not name_or_id in self:
                return abort(404, "Not found")

            return self[name_or_id]

        return name_or_id

    def media_list_remove(self, list_id):
        list_id = self.get_list_id(list_id)

        my_list = DB_MediaList.objects(pk=list_id).first()
        if my_list.username != current_user.username:
            return abort(401, "Unauthorized")

        my_list.delete()
        return {'media_list': 'deleted'}

    def media_list_get(self, list_id):
        list_id = self.get_list_id(list_id)

        my_list = DB_MediaList.objects(pk=list_id).first()
        my_list.check_permissions()

        ret = mongo_to_dict_helper(my_list)
        return ret

    def get_every_media_list(self):
        ret = mongo_to_dict_helper(self)
        return ret

    def clear_all(self):
        """ Deletes every media list for this object """

        for list_id in self:
            if not self[list_id]:
                continue

            try:
                my_list = DB_MediaList.objects(pk=self[list_id]).first()
                if not my_list:
                    continue

                self[list_id] = None
                if my_list.username != current_user.username:
                    print_r(" We can only delete our own collections ")
                    continue

            except Exception as e:
                print_exception(e, "Crashed cleaning user data ")

        my_list = DB_MediaList.objects(username=current_user.username)
        my_list.delete()

        return self.get_every_media_list()
