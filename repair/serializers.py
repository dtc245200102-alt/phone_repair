from rest_framework import serializers
from .models import Customer, Device, RepairTicket, Part, TicketPart, Warranty

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'

class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = '__all__'

class RepairTicketSerializer(serializers.ModelSerializer):
    device_info = DeviceSerializer(source='device', read_only=True)

    class Meta:
        model = RepairTicket
        fields = '__all__'

class PartSerializer(serializers.ModelSerializer):
    class Meta:
        model = Part
        fields = '__all__'

class WarrantySerializer(serializers.ModelSerializer):
    class Meta:
        model = Warranty
        fields = '__all__'

class TicketPartSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketPart
        fields = '__all__'