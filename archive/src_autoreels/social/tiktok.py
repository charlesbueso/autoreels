"""TikTok Content Posting API — TODO.

Requires TikTok Developer Account + app review approval.
See: https://developers.tiktok.com/doc/content-posting-api-get-started

For now, reels are posted to Discord for manual TikTok sharing.
"""

# TODO: Implement TikTok Content Posting API once app is approved.
# The flow will be:
# 1. POST /v2/post/publish/video/init/ — get upload URL
# 2. PUT video file to the upload URL
# 3. POST /v2/post/publish/video/ — publish
