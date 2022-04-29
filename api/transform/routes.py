import validators

from flask import abort, send_file
from flask_login import current_user

from api.api_redis import api_rq
from api.transform import blueprint
from api.media.models import File_Tracking
from api.media.routes import get_media_path
from api import get_response_formatted, get_response_error_formatted


def get_postfix(operation, transformation):
    """ Checks if the name is only alphanumeric, and has hiphens or underscores """

    postfix = operation + "_" + transformation
    if not validators.slug(postfix):
        abort(400, "Malformed operation")

    return "." + postfix + ".PNG"


@blueprint.route('/<string:operation>/<string:transformation>/<string:media_id>', methods=['GET', 'POST'])
def api_convert_image_to_format(operation, transformation, media_id):
    """Returns a JOB ID for the task of fetching this resource. It calls RQ to get the task of converting the file done.
    ---
    tags:
      - transform
    schemes: ['http', 'https']
    deprecated: false
    definitions:
      request_url:
        type: object
    parameters:
        - in: query
          name: request_url
          schema:
            type: string
          description: A valid URL that contains a file format on it.
    responses:
      200:
        description: Returns a job ID
        schema:
          id: Job ID
          type: object
          properties:
            job_id:
              type: string
    """

    if transformation not in ["PNG", "JPG", "rotate_right", "rotate_left", "thumbnail", "blur", "flop", "median"]:
        return get_response_error_formatted(500, {"error_msg": "SERVER CANNOT UNDERSTAND THIS TRANSFORMATION!"})

    my_file = File_Tracking.objects(pk=media_id).first()
    if not my_file:
        return get_response_error_formatted(404, {"error_msg": "FILE NOT FOUND"})

    post_fix = get_postfix(operation, transformation)
    abs_path = get_media_path() + my_file.file_path

    data = {
        'media_id': media_id,
        'media_path': abs_path,
        'operation': operation,
        'target_path': abs_path + post_fix,
        'transformation': transformation,
        'post_fix': post_fix,
        'media_id': media_id
    }

    job = api_rq.call("worker.convert_image", data)
    if not job:
        return get_response_error_formatted(401, {'error_msg': "Failed reaching the services."})

    ret = {'status': 'success', 'job_id': job.id}
    return get_response_formatted(ret)


@blueprint.route('/job/<string:job_id>', methods=['GET'])
def api_get_media_from_job(job_id):
    """Returns the state of a job_id and it's result
    ---
    tags:
      - media
    schemes: ['http', 'https']
    deprecated: false
    definitions:
      request_url:
        type: object
    parameters:
        - in: query
          name: job_id
          schema:
            type: string
          description: A valid ID for a job in the system.
    responses:
      200:
        description: If the job has not completed it will return a json object.
        schema:
          id: Job ID
          type: object
          properties:
            job_id:
              type: string
            result:
              type: string
            job_status:
              type: string

      500:
        description: There was some problem performing this task
        schema:
          id: Job ID
          type: object
          properties:
            error_msg:
              type: string

    """
    job = api_rq.fetch_job(job_id)

    status = job.get_status()
    if status == "failed":
        return get_response_error_formatted(
            500, {'error_msg': "There was some problem performing this task, please contact an administrator."})

    ret = {'status': 'success', 'job_id': job_id, 'job_status': status}
    if status != "finished":
        return get_response_formatted(ret)

    ret['result'] = job.result
    return get_response_formatted(ret)


@blueprint.route('/get/<string:job_id>', methods=['GET'])
def api_get_result_job(job_id):
    """Returns the state of a job_id and it's result
    ---
    tags:
      - media
    schemes: ['http', 'https']
    deprecated: false
    definitions:
      request_url:
        type: object
    parameters:
        - in: query
          name: job_id
          schema:
            type: string
          description: A valid ID for a job in the system.
    responses:
      200:
        description: If the job has not completed it will return a json object
        schema:
          id: Job ID
          type: object
          properties:
            job_id:
              type: string
            result:
              type: string
            job_status:
              type: string

      500:
        description: There was some problem performing this task
        schema:
          id: Job ID
          type: object
          properties:
            error_msg:
              type: string

    """
    job = api_rq.fetch_job(job_id)

    status = job.get_status()
    if status == "failed":
        if is_api_call():
            return get_response_error_formatted(
                500, {'error_msg': "There was some problem performing this task, please contact an administrator."})
        else:
            return redirect("/static/images/placeholder.jpg")

    if status != "finished":
        if is_api_call():
            return get_response_formatted({'status': 'success', 'job_id': job_id, 'job_status': status})
        else:
            return redirect("/static/images/placeholder.jpg")

        return (ret)

    res = job.result

    my_file = File_Tracking.objects(pk=res['media_id']).first()
    if not my_file:
        if is_api_call():
            return get_response_error_formatted(404, {"error_msg": "FILE NOT FOUND"})
        else:
            return redirect("/static/images/placeholder.jpg")

    if not my_file.is_public and my_file.username != current_user.username:
        if is_api_call():
            return get_response_error_formatted(401, {"error_msg": "FILE IS PRIVATE!"})
        else:
            return redirect("/static/images/placeholder_private.jpg")

    post_fix = get_postfix(res['operation'], res['transformation'])
    abs_path = get_media_path() + my_file.file_path + post_fix
    return send_file(abs_path, attachment_filename=my_file.file_name + post_fix)