import json
from neftecode.composition.training import train

def handle(args, parser, root, out):
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    return train(root, out, cfg)
