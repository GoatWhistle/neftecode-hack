"""CLI handlers for demo."""
from neftecode.composition.demo import make_demo
from neftecode.composition.decision import make_demo_service
from neftecode.presentation.web.server import serve as serve_demo

def demo(args, parser, root, out):
    return make_demo(root, out)

def serve(args, parser, root, out):
    return serve_demo(make_demo_service(root), args.port)
