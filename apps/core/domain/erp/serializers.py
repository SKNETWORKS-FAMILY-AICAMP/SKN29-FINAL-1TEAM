from rest_framework import serializers

from .models import ErpVoucher


class ErpVoucherSerializer(serializers.ModelSerializer):
    voucherPayload = serializers.JSONField(source="voucher_payload", read_only=True)

    class Meta:
        model = ErpVoucher
        fields = ["id", "settlement", "voucherPayload", "status", "created_at"]
