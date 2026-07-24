from rest_framework import serializers

from .models import ErpVoucher


class ErpVoucherSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErpVoucher
        fields = ["id", "settlement", "voucher_payload", "status", "created_at"]
