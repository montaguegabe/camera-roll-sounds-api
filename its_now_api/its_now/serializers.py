from rest_framework import serializers


class PresentMomentContextSerializer(serializers.Serializer):
    current_location = serializers.CharField(allow_blank=False)
    current_date_time = serializers.CharField(allow_blank=False)
    user_name = serializers.CharField(allow_blank=False)


class PhotoInputSerializer(serializers.Serializer):
    image = serializers.CharField(allow_blank=False)
    year = serializers.IntegerField(min_value=1900, max_value=3000)


class ProcessImagesRequestSerializer(serializers.Serializer):
    image = serializers.CharField(required=False, allow_blank=False)
    images = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        allow_empty=False,
    )
    photos = PhotoInputSerializer(many=True, required=False)
    current_location = serializers.CharField(required=False, allow_blank=False)
    current_date_time = serializers.CharField(required=False, allow_blank=False)
    current_date = serializers.CharField(required=False, allow_blank=False)
    user_name = serializers.CharField(required=False, allow_blank=False)
    present_moment = PresentMomentContextSerializer(required=False)
