import os
import redis
import requests
from wand.image import Image

# https://www.pythonpool.com/imagemagick-python/

from rq import Worker, Queue, Connection

listen = ['default']

redis_url = os.getenv('REDISTOGO_URL', 'redis://localhost:6379')

conn = redis.from_url(redis_url)


def is_worker_alive(msg):
    print("I AM ALIVE " + msg)
    return msg


def convert_image(json):
    """ Converts into a different format and returns the file path to retrieve the image
        More transformations here: https://docs.wand-py.org/en/0.5.9/guide/transform.html
    """

    trf = json['transformation']
    media_id = json['media_id']
    operation = json['operation']
    image_path = json['media_path']
    target_path = json['target_path']

    try:
        image = Image(filename=image_path)
        if operation == "convert":
            print(" CONVERT " + image_path + " INTO " + trf)
            image = image.convert(trf)

        elif operation == "transform":
            if trf == "rotate_right":
                image.rotate(90)
            elif trf == "rotate_left":
                image.rotate(-90)
            elif trf == "flop":
                image.flop()

        elif operation == "filter":
            if trf == "blur":
                image.blur(sigma=4)
            elif trf == "median":
                with image.clone() as right:
                    right.statistic("median", width=8, height=5)
                    image.extent(width=image.width * 2)
                    image.composite(right, top=0, left=right.width)

        image.save(filename=target_path)
        if os.path.exists(target_path):
            print(operation + " => " + trf + " WAS SUCCESSFUL ")
            return {'state': 'success', 'operation': operation, 'transformation': trf, 'media_id': media_id}

    except Exception as e:
        print(str(e))
        print(operation + " => " + trf + " CRASHED ")

    print(operation + " => " + trf + " FAILED ")
    return {'state': 'error', 'operation': operation, 'transformation': trf, 'media_id': media_id}

def fetch_url_image(request_url):
    r = requests.get(request_url, allow_redirects=True)
    content_type = r.headers.get('content-type')

    print("[" + content_type + "]")
    if not content_type.startswith('image'):
        print("CONTENT TYPE IS NOT AN IMAGE ")
        return {'state': 'error'}

    print("Process file, check if image")
    return {'state': 'success'}

if __name__ == '__main__':
    with Connection(conn):
        worker = Worker(list(map(Queue, listen)))
        worker.work()