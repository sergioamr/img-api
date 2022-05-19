import time
import random
import bcrypt
import binascii
import datetime
import validators

from api.user import blueprint
from api.print_helper import *

from api import get_response_formatted, get_response_error_formatted, api_key_or_login_required, api_key_login_or_anonymous

from flask import jsonify, request, Response, redirect, abort
from api.tools import generate_file_md5, ensure_dir, is_api_call
from api.query_helper import mongo_to_dict_helper

from .models import User
from .galleries import DB_MediaList

from mongoengine.queryset import QuerySet
from mongoengine.queryset.visitor import Q

from flask_login import current_user, login_user, logout_user


def get_user_from_request():
    user = None
    username = None

    if request.method == 'POST':
        form = request.json

        email = form['email'].strip()
        if 'username' in form:
            username = form['username'].strip()

        password = form['password']
    else:
        email = request.args.get("email").strip()
        username = request.args.get("username").strip()
        password = request.args.get("password")

    if not password:
        return get_response_error_formatted(401, {'error_msg': "Please provide a password."})

    if not email:
        return get_response_error_formatted(401, {'error_msg': "Please provide an email."})

    if username:
        # Users tend to add extra spaces, frontend should take care of it, but the user calling the API might not write the username properly.
        username = username.strip()
        if not validators.slug(username):
            return get_response_error_formatted(401, {'error_msg': "Sorry, please contact an admin."})

        user = User.objects(username__iexact=username).first()
    else:
        email = email.strip()
        if not validators.email(email):
            return get_response_error_formatted(401, {'error_msg': "Sorry, please contact an admin."})

        user = User.objects(email__iexact=email).first()

    if not user:
        return get_response_error_formatted(401, {'error_msg': "Account not found!"})

    user_pass = binascii.unhexlify(user.password)
    if not bcrypt.checkpw(password.encode('utf-8'), user_pass):
        return get_response_error_formatted(
            401, {'error_msg': "Wrong user or password, please try again or create a new user!"})

    if not user.active:
        return get_response_error_formatted(401, {'error_msg': "Please wait for an admin to give you access."})

    return user


@blueprint.route('/login', methods=['GET', 'POST'])
def api_login_user():
    """Login an user into the system
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    parameters:
        - in: query
          name: email
          schema:
            type: string
          description: A valid email
        - in: query
          name: password
          schema:
            type: string
          description: A vaild password
    definitions:
      user:
        type: object
    definitions:
      user_file:
        type: object
    responses:
      200:
        description: Logins the user
        schema:
          id: Token callback response
          type: object
          properties:
            msg:
                type: string
            status:
                type: string
            token:
                type: string
      401:
        description: User is not authorized to perform this operation, read the error message
        schema:
          id: Login error
          type: object
          properties:
            msg:
                type: string
            status:
                type: string
    """

    user = get_user_from_request()
    if isinstance(user, Response):
        return user

    login_user(user, remember=True)

    token = user.generate_auth_token()
    return get_response_formatted({'status': 'success', 'msg': 'hello user', 'token': token})


def split_addr(emailStr, encoding):
    import re

    regexStr = r'^([^@]+)@[^@]+$'
    matchobj = re.search(regexStr, emailStr)
    if not matchobj is None:
        print("EMAIL ADDRESS " + matchobj.group(1))
    else:
        print("Did not match")
        return None, None

    return [matchobj.group(0), matchobj.group(1)]


def sanitize_address(addr, encoding):
    """
    Format a pair of (name, address) or an email address string.
    """
    from email.utils import parseaddr
    from email.errors import InvalidHeaderDefect, NonASCIILocalPartDefect
    from email.header import Header
    from email.headerregistry import Address

    if not isinstance(addr, tuple):
        addr = parseaddr(addr)
    nm, addr = addr
    localpart, domain = None, None
    nm = Header(nm, encoding).encode()

    try:
        try:
            addr.encode('ascii')
        except UnicodeEncodeError:  # IDN or non-ascii in the local part
            localpart, domain = split_addr(addr, encoding)

        # An `email.headerregistry.Address` object is used since
        # email.utils.formataddr() naively encodes the name as ascii (see #25986).
        if localpart and domain:
            address = Address(nm, username=localpart, domain=domain)
            return str(address)

        try:
            address = Address(nm, addr_spec=addr)
        except (InvalidHeaderDefect, NonASCIILocalPartDefect):
            localpart, domain = split_addr(addr, encoding)
            address = Address(nm, username=localpart, domain=domain)

    except Exception as err:
        print(" Address not valid " + str(err))
        return None

    return str(address)


def check_email(email):
    # Regex test
    import re
    if not email:
        return False

    # As it is, it will support more than one plus in the string, FIX is required
    match = re.match('^[_a-z0-9-\+]+(\.[_a-z0-9-\+]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,4})$', email)
    if match == None:
        return False

    return True


def get_validated_email(email):
    # https://stackoverflow.com/questions/8022530/how-to-check-for-valid-email-address

    if not validators.email(email):
        return get_response_error_formatted(400, {'error_msg': "Please provide a valid email"})

    try:
        if not email or len(email) == 0:
            return get_response_error_formatted(400, {'error_msg': "Please provide a valid email"})

        email_clean = sanitize_address(email, 'iso-8859-1')
        if not email_clean or not check_email(email_clean):
            return get_response_error_formatted(400,
                                                {'error_msg': "Please provide a valid email " + email + " is no valid"})

        print(" Email after sanitize_address " + str(email_clean))
        return email_clean

    except Exception as e:
        return get_response_error_formatted(400,
                                            {'error_msg': "Please provide a valid email " + email + " is no valid"})

    return None


def is_password_valid(password):
    """ Check password policies
        We should check a dictionary and length
    """

    if len(password) < 8:
        return False

    return True


@blueprint.route('/create', methods=['GET', 'POST'])
def api_create_user_local():
    """ User creation
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    parameters:
        - in: query
          name: email
          schema:
            type: string
          description: A valid email that will define username
        - in: query
          name: password
          schema:
            type: string
          description: A vaild password
    definitions:
      user:
        type: object
    responses:
      200:
        description: Returns if the user was successfully created
        schema:
          id: Standard status message
          type: object
          properties:
            msg:
                type: string
            status:
                type: string
            timestamp:
                type: string
            time:
                type: integer

    """

    print("======= CREATE USER LOCAL =============")

    if request.method == 'POST':
        form = request.json
        first_name = form['first_name']
        last_name = form['last_name']

        email = form['email'].strip().lower()
        username = form['username'].strip().lower()
        password = form['password']
    else:
        first_name = request.args.get("first_name")
        last_name = request.args.get("last_name")

        email = request.args.get("email").strip().lower()
        username = request.args.get("username").strip()
        password = request.args.get("password")

    if first_name: first_name = first_name.strip()
    if last_name: last_name = last_name.strip()

    if len(username) < 4:
        return get_response_error_formatted(401, {'error_msg': "Your username is too short"})

    if not validators.slug(username):
        return get_response_error_formatted(401, {'error_msg': "Your username has non valid characters"})

    if not is_password_valid(password):
        return get_response_error_formatted(401, {'error_msg': "Password has to be at least 8 characters long"})

    hashpass = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    user = User.objects(Q(username__iexact=username) | Q(email__iexact=email)).first()
    if user:
        # Our user might already been created, we check the password against the system and we return a token in case of being the same.
        if user['email'] == email and user['username'] == username:
            user_pass = binascii.unhexlify(user.password)
            if bcrypt.checkpw(password.encode('utf-8'), user_pass):
                print(" User is already on the system with this credentials, we return a token ")

                ret = {
                    'username': username,
                    'email': email,
                    'duplicate': True,
                    'status': 'success',
                    'msg': 'You were already registered, here is our token of gratitude',
                    'token': user.generate_auth_token()
                }

            return get_response_formatted(ret)

        return get_response_error_formatted(401, {'error_msg': "User already on the system, would you like to login?"})

    email = get_validated_email(email)
    if isinstance(email, Response):
        return email

    user_obj = {
        'first_name': first_name,
        'last_name': last_name,
        'password': hashpass.hex(),
        'username': username,
        'email': email,

        # Active by default, we don't have validation on this system
        'active': True,
    }

    user = User(**user_obj)
    user.save()

    ret = {
        'username': username,
        'email': email,
        'status': 'success',
        'msg': 'Thanks for registering',
        'token': user.generate_auth_token()
    }
    return get_response_formatted(ret)


@blueprint.route('/remove', methods=['GET', 'POST', 'DELETE'])
def api_remove_user_local():
    """ An user can delete its account
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    parameters:
        - in: query
          name: email
          schema:
            type: string
          description: A valid email
        - in: query
          name: password
          schema:
            type: string
          description: A vaild password
    definitions:
      user:
        type: object
    responses:
      200:
        description: Returns if the user was successfully deleted
        schema:
          id: Standard status message
          type: object
          properties:
            msg:
                type: string
            status:
                type: string
    """
    print("======= DELETE USER LOCAL =============")

    user = get_user_from_request()
    if isinstance(user, Response):
        return user

    user.delete()
    return get_response_formatted({'status': 'success', 'msg': 'user deleted'})


@blueprint.route('/token', methods=['GET'])
@api_key_or_login_required
def get_auth_token():
    """ Gets a token that an user can user to upload and perform operations.

    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    parameters:
        - in: query
          name: token
          schema:
            type: string
          description: (Optional) If there is a token on the call, it will check if it is validity

    definitions:
      token:
        type: object
    responses:
      200:
        description: Returns the user token
        schema:
          id: Token
          type: object
          properties:
            token:
                type: string
    """

    token = request.args.get("key")
    if not token:
        token = current_user.generate_auth_token()
        return get_response_formatted({'token': token, 'username': current_user.username})

    user = User.verify_auth_token(token)
    if isinstance(user, Response):
        return user

    login_user(user, remember=True)
    return get_response_formatted({'token': token, 'username': user.username, 'status': 'success'})


@blueprint.route('/get/<string:user_id>', methods=['GET'])
@api_key_login_or_anonymous
def api_get_user_by_username(user_id):
    """ Returns the current user being logged in
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    parameters:
        - in: query
          name: username
          schema:
            type: string
          description: Username, you can use no user name, that would be you. Or an alias called "me" that will also be you.
    definitions:
      user_file:
        type: object
    responses:
      200:
        description: Returns the username in a message in a serialized form
        schema:
          id: Standard status message
          type: object
          properties:
            username:
                type: string
      401:
        description: There is a problem with this user
        schema:
          id: Login error
          type: object
          properties:
            msg:
                type: string
            status:
                type: string
    """

    if not user_id or user_id == "me":
        if not current_user.is_authenticated:
            return get_response_error_formatted(401, {'error_msg': "Please login or create an account."})

        if not current_user or not current_user.username:
            return get_response_error_formatted(401, {'error_msg': "Account not found."})

        current_user.check_in_usage()
        return get_response_formatted({'user': current_user.serialize()})

    user = User.objects(username__iexact=user_id).first()
    if not user or not user.username:
        return get_response_error_formatted(401, {'error_msg': "Account not found."})

    return get_response_formatted({'user': user.serialize()})


@blueprint.route('/get', methods=['GET'])
def api_get_current_user():
    return api_get_user_by_username(None)


def generate_random_name():
    """ Generates a random name so we can use it for the anonymous user.
        This name should come from a dictionary like 3words
    """
    from services.my_dictionary import words

    l = len(words)

    random.seed(time.clock())

    my_user_name = ""
    while not my_user_name:
        for i in range(0, 3):
            r = random.randint(0, l - 1)
            if i != 0:
                my_user_name += "_"

            my_user_name += words[r]

        if User.objects(username=my_user_name).first():
            print("Found collision " + my_user_name)
            my_user_name = ""

    print("Your user name " + my_user_name)
    return my_user_name.upper()


def generate_random_user():
    """ We generate a random user for files which are going to be anonymous
        The user will be able to modify the files until they delete their cookies
    """

    random_name = generate_random_name()
    password = random_name + str(datetime.datetime.now())
    user_obj = {
        'password': bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).hex(),
        'username': random_name,
        'email': random_name + "@img-api.com",
        'is_anon': True,
        'active': True,
    }

    user = User(**user_obj)
    user.save()

    login_user(user, remember=True)
    return user


@blueprint.route('/logout', methods=['GET', 'POST'])
def api_user_logout():
    """ User logout, remove cookies
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    definitions:
      user:
        type: object
    responses:
      200:
        description: Just logs out the user
    """

    if not current_user.is_authenticated:
        return get_response_error_formatted(401, {'error_msg': "Please login or create an account."})

    logout_user()

    if is_api_call():
        return get_response_formatted({'status': 'success', 'msg': 'user logged out'})

    return redirect("/")


@blueprint.route('/media/<string:media_id>/<string:action>/<string:my_list>', methods=['GET'])
@api_key_or_login_required
def api_set_this_media_into_an_action(media_id, action, my_list):
    """ Performs an action for a particular media in a list.
        This can be, add it to favourites, or likes, dislikes, add it to a playlist...
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    parameters:
        - in: query
          name: media_id
          schema:
            type: string
          description: The media

        - in: query
          name: action
          schema:
            type: string
          description: append, remove, toggle

        - in: query
          name: my_list
          schema:
            type: string
          description: Internal media list

    definitions:
      user_file:
        type: object
    """
    from api.media.routes import api_set_media_private_posts_json

    if action == "toggle" and my_list == "is_public":
        return api_set_media_private_posts_json(media_id, action)

    ret = current_user.action_on_list(media_id, action, my_list)
    return get_response_formatted(ret)


@blueprint.route('/<string:username>/list/<string:list_id>/<string:action>/<string:image_type>', methods=['GET'])
@blueprint.route('/<string:username>/list/<string:list_id>/<string:action>', methods=['GET', 'DELETE'])
@api_key_login_or_anonymous
def api_actions_on_list(username, list_id, action, image_type=None):
    """ Performs an action for a list
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    parameters:
        - in: query
          name: username
          schema:
            type: string
          description: Username to perform an action. An anonymous user can ask for public media lists

        - in: query
          name: list_id
          schema:
            type: string
          description: The media

        - in: query
          name: action
          schema:
            type: string
          description: create, remove, get, add, set_cover, set_background

        - in: query
          name: no_populate
          schema:
            type: string
          description: Do not add all the media_files and leave the media_list

    definitions:
      user_file:
        type: object
    responses:
      200:
        description: Returns a list of media_files
      400:
        description: The list is not found
      401:
        description: The list is private to that particular user
    """

    from api.media.routes import api_populate_media_list, api_get_user_photostream

    if list_id == "undefined":
        return get_response_error_formatted(400, {'error_msg': "Wrong frontend."})

    if current_user.is_authenticated:
        if username == 'me' or current_user.username == username:
            if action == 'remove':
                res = current_user.media_list_remove(list_id)
                return get_response_formatted(res)

            # Not supported through this API
            #if action == 'add':
            #    ret = current_user.action_on_list(media_id, action, my_list)
            #    return get_response_formatted({})

    if action == 'get':

        # We have the special category "stream" which is the photo stream of the user.
        # That will be their public photos if you are a third party user, or all your pictures if it is you.
        if list_id == "stream":
            return api_get_user_photostream(username)

        # Galleries owned by you will display everything
        if current_user.is_authenticated and (username == 'me' or current_user.username == username):
            ret = current_user.galleries.media_list_get(list_id, image_type)
        else:
            # Galleries owned by a third pary will only display public facing pictures
            user = User.objects(username__iexact=username).first()
            if not user:
                return get_response_error_formatted(404, {'error_msg': "User not found."})

            ret = user.galleries.media_list_get(list_id, image_type)

        # We populate the list with results, and not only media IDs
        # The user might want to get a clean view without extra information, to maybe display only the tile.
        populate = not request.args.get("no_populate", False)
        if populate:
            media_list = [media['media_id'] for media in ret['media_list']]
            ret.update(api_populate_media_list(username, media_list))

        return get_response_formatted(ret)

    return get_response_error_formatted(400, {'error_msg': "Wrong parameters."})


@blueprint.route('/list/get_by_id/<string:list_id>/<string:image_type>', methods=['GET'])
@blueprint.route('/list/get_by_id/<string:list_id>', methods=['GET'])
@api_key_or_login_required
def api_get_by_list_id(list_id, image_type=None):
    """ Gets all the list of media this list has, if it is public
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    definitions:
      user_file:
        type: object
    responses:
      200:
        description: Returns a the list given by id if it is public or you are the owner
      404:
        description: Missing gallery
      401:
        description: Gallery is not public and it is not yours

    """
    from api.media.routes import api_populate_media_list

    the_list = DB_MediaList.objects(pk=list_id).first()
    if not the_list:
        return abort(404, "Missing Gallery")

    if current_user.is_authenticated and the_list.username != current_user.username:
        if not the_list.is_public:
            return abort(401, "Unauthorized")

    ret = mongo_to_dict_helper(the_list)

    arr = the_list.get_as_list()
    if image_type == "random":
        arr = [random.choice(arr)]

    ret.update(api_populate_media_list(the_list.username, arr))

    return get_response_formatted(ret)


@blueprint.route('/list/get', methods=['GET'])
@api_key_or_login_required
def api_get_all_the_lists():
    """ Gets all the list of media lists this user has. It is a private call for this user
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    definitions:
      user_file:
        type: object
    responses:
      200:
        description: Returns a list of lists
    """

    ret = current_user.galleries.get_every_media_list()

    if False:
        ret['galleries'].pop('favs', None)

    return get_response_formatted(ret)


@blueprint.route('/list/create', methods=['POST'])
@api_key_or_login_required
def api_create_a_new_list():
    """ Gets all the list of media lists this user has. It is a private call for this user
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    definitions:
      user_file:
        type: object
    responses:
      200:
        description: Returns the created gallery
      409:
        description: The gallery already exists and there is a conflict
    """

    g = current_user.galleries

    json = request.json
    title = json['title']
    gallery_name = g.get_safe_gallery_name(title)
    if len(gallery_name) <= 3:
        return get_response_error_formatted(400, {'error_msg': "Gallery name has to be longer than that"})

    ret = g.exists(gallery_name)
    print_b("Creating " + gallery_name)

    if ret:
        print_r("Duplicated")
        return get_response_error_formatted(409, {'error_msg': "Gallery already exists with that name"})  # Conflict

    ret = g.create(current_user.username, gallery_name, json)
    current_user.save(validate=False)
    ret['username'] = current_user.username

    return get_response_formatted(ret)

@blueprint.route('/list/update', methods=['POST'])
@api_key_or_login_required
def api_update_a_list():
    """ Updates the list information, we only accept calls from this user
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    definitions:
      user_file:
        type: object
    responses:
      200:
        description: Returns the updated library
      401:
        description: User cannot update this library
    """

    ret = current_user.galleries.update(request.json)
    current_user.save(validate=False)
    ret['username'] = current_user.username

    return get_response_formatted(ret)

@blueprint.route('/list/clear', methods=['GET', 'DELETE'])
@api_key_or_login_required
def api_delete_all_the_lists():
    """ Deletes every list that this user has. Mainly for testing purposes
    ---
    tags:
      - user
    schemes: ['http', 'https']
    deprecated: false
    definitions:
      user_file:
        type: object
    """

    ret = current_user.galleries.clear_all(current_user.username)
    current_user.save()
    return get_response_formatted(ret)
