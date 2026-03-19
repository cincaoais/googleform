import json
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET


def index(request):
    return render(request, "formfiller/index.html")


@csrf_exempt
@require_POST
def api_parse(request):
    """Parse a Google Form URL and return field structure."""
    try:
        body = json.loads(request.body)
        url = body.get("url", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"success": False, "error": "Invalid request body"}, status=400)

    if not url:
        return JsonResponse({"success": False, "error": "URL is required"}, status=400)

    if "docs.google.com/forms" not in url:
        return JsonResponse({"success": False, "error": "Not a valid Google Forms URL"}, status=400)

    try:
        from .form_parser import parse_form
        result = parse_form(url)
        return JsonResponse({"success": True, "form": result})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@csrf_exempt
@require_POST
def api_submit(request):
    """Start a batch submission job."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"success": False, "error": "Invalid request body"}, status=400)

    from .form_submitter import submitter_instance
    job_id = submitter_instance.start_job(body)
    return JsonResponse({"success": True, "job_id": job_id})


@csrf_exempt
@require_POST
def api_stop(request, job_id):
    """Stop a running submission job."""
    from .form_submitter import submitter_instance
    stopped = submitter_instance.stop_job(job_id)
    return JsonResponse({"success": stopped})


@require_GET
def api_stream(request, job_id):
    """SSE endpoint for real-time progress updates."""
    from .form_submitter import submitter_instance

    def event_stream():
        import queue as queue_module
        q = submitter_instance.subscribe(job_id)
        if q is None:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
            return
        try:
            while True:
                try:
                    data = q.get(timeout=30)
                except queue_module.Empty:
                    yield ": heartbeat\n\n"
                    continue
                yield f"data: {json.dumps(data)}\n\n"
                if data.get("type") in ("complete", "stopped", "error"):
                    break
        finally:
            submitter_instance.unsubscribe(job_id, q)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
