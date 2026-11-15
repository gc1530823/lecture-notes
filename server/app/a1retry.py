"""큰 무료 서버(A1.Flex 4코어·24GB) 자동 만들기: 오라클에 빈자리가 날 때까지 이 서버가 2분마다 대신 시도한다.

클라우드 셸은 창을 오래 두면 꺼져서 재시도가 멈춘다. 이 서버는 24시간 켜져 있으니 여기서 돈다.
관리자 페이지에서 오라클 API 키(설정 미리보기 값 + 개인 키)와 새 서버 설치 스크립트를 한 번 넣으면 된다.
성공하면 스스로 멈추고, 만든 서버를 관리자 페이지에 보여 준다. 비용 0원 (Always Free 크기만 만든다).
"""

from __future__ import annotations

import base64
import json
import logging
import time

log = logging.getLogger(__name__)
SHAPE = "VM.Standard.A1.Flex"
OCPUS, MEMORY_GB = 4, 24
NAME = "lune2"


def status(db) -> dict:
    return json.loads(db.get_setting("a1_status") or "{}")


def _save(db, **change) -> dict:
    st = {**status(db), **change}
    db.set_setting("a1_status", json.dumps(st, ensure_ascii=False))
    return st


def configured(db) -> bool:
    return bool(db.get_setting("a1_config")) and bool(db.get_setting("a1_init"))


def _clients(db):
    import oci

    cfg = json.loads(db.get_setting("a1_config") or "{}")
    config = {"user": cfg["user"], "fingerprint": cfg["fingerprint"], "tenancy": cfg["tenancy"],
              "region": cfg["region"], "key_content": cfg["key"]}
    oci.config.validate_config(config)
    return config, oci.core.ComputeClient(config), oci.core.VirtualNetworkClient(config), oci.identity.IdentityClient(config)


def try_once(db) -> dict:
    """한 번 시도: 성공하면 done=True, 자리가 없으면 메시지만 남긴다"""
    import oci

    st = status(db)
    if st.get("done"):
        return st
    config, compute, network, identity = _clients(db)
    tenancy = config["tenancy"]
    ad = identity.list_availability_domains(tenancy).data[0].name
    subnet = next(iter(network.list_subnets(tenancy).data), None)
    if subnet is None:
        return _save(db, message="서브넷을 찾지 못했어요 (오라클 콘솔에서 VCN을 먼저 만들어야 해요)", at=time.time())
    images = compute.list_images(tenancy, operating_system="Canonical Ubuntu", operating_system_version="24.04",
                                 shape=SHAPE, sort_by="TIMECREATED", sort_order="DESC").data
    if not images:
        return _save(db, message="우분투 24.04 이미지를 찾지 못했어요", at=time.time())
    details = oci.core.models.LaunchInstanceDetails(
        compartment_id=tenancy, availability_domain=ad, display_name=NAME, shape=SHAPE,
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=OCPUS, memory_in_gbs=MEMORY_GB),
        source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=images[0].id),
        create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet.id, assign_public_ip=True),
        metadata={"user_data": base64.b64encode((db.get_setting("a1_init") or "").encode()).decode()})
    tries = st.get("tries", 0) + 1
    try:
        inst = compute.launch_instance(details).data
    except oci.exceptions.ServiceError as exc:
        msg = {"InternalError": "아직 빈자리가 없어요 (Out of host capacity)",
               "TooManyRequests": "너무 자주 물어봐서 잠시 쉬어요"}.get(exc.code, f"{exc.code}: {exc.message[:120]}")
        if "capacity" in (exc.message or "").lower():
            msg = "아직 빈자리가 없어요 (Out of host capacity)"
        return _save(db, tries=tries, message=msg, at=time.time())
    log.warning("큰 서버를 만들었어요: %s", inst.id)
    # 다 만들었으니 오라클 열쇠·설치 스크립트(키 포함)는 지운다 (백업에 남지 않게)
    db.set_setting("a1_config", None)
    db.set_setting("a1_init", None)
    return _save(db, tries=tries, done=True, enabled=False, instance=inst.id, message="큰 서버를 만들었어요! 15분쯤 뒤 설치가 끝나요.",
                 at=time.time())


def due(db, every: float = 120) -> bool:
    st = status(db)
    return bool(st.get("enabled")) and not st.get("done") and configured(db) and time.time() - st.get("at", 0) >= every
