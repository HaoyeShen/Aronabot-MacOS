"""Native publishing facade; reading/previewing never publishes a post."""
def publish(adapter,text,image_path=None,*,dry_run=False):
    return adapter.publish_moment(text,image_path,dry_run=dry_run)
