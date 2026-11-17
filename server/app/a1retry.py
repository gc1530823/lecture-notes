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
# 큰 자리가 없으면 작은 크기라도 먼저 만들고(1코어·6GB도 지금 서버의 6배 메모리), 나중에 자리가 나면 2 → 4코어로 키운다
SIZES = [(4, 24), (2, 12), (1, 6)]
SETTLE = 30 * 60        # 만든 뒤 설치(약 15분)가 끝나기 전에는 키우지 않는다 (키우면 다시 켜지므로)
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


def _capacity_msg(exc) -> str:
    if "capacity" in (exc.message or "").lower() or exc.code == "InternalError":
        return "아직 빈자리가 없어요 (Out of host capacity)"
    if exc.code == "TooManyRequests":
        return "너무 자주 물어봐서 잠시 쉬어요"
    return f"{exc.code}: {(exc.message or '')[:120]}"


def _finish(db, **change) -> dict:
    # 4코어까지 다 키웠으니 오라클 열쇠·설치 스크립트(키 포함)는 지운다 (백업에 남지 않게)
    db.set_setting("a1_config", None)
    db.set_setting("a1_init", None)
    return _save(db, done=True, enabled=False, **change)


def _grow(db, st: dict, compute) -> dict:
    """이미 만든 작은 서버를 한 단계 이상 키워 본다 (자리가 나면). 키우면 서버가 잠깐 다시 켜진다"""
    import oci

    tries = st.get("tries", 0) + 1
    inst = compute.get_instance(st["instance"]).data
    if inst.lifecycle_state != "RUNNING":
        return _save(db, tries=tries, message=f"서버 상태가 {inst.lifecycle_state} 라 키우기를 기다려요", at=time.time())
    if time.time() - st.get("created_at", 0) < SETTLE:
        return _save(db, tries=tries, message=f"{st.get('ocpus')}코어로 만들었어요. 설치가 끝나면 더 키워 볼게요", at=time.time())
    last = None
    for ocpus, mem in SIZES:
        if ocpus <= st.get("ocpus", 0):
            break
        try:
            compute.update_instance(st["instance"], oci.core.models.UpdateInstanceDetails(
                shape_config=oci.core.models.UpdateInstanceShapeConfigDetails(ocpus=ocpus, memory_in_gbs=mem)))
        except oci.exceptions.ServiceError as exc:
            last = exc
            continue
        log.warning("큰 서버를 %s코어로 키웠어요", ocpus)
        if ocpus >= OCPUS:
            return _finish(db, tries=tries, ocpus=ocpus, message="4코어·24GB로 다 키웠어요! (잠깐 다시 켜져요)", at=time.time())
        return _save(db, tries=tries, ocpus=ocpus, message=f"{ocpus}코어·{mem}GB로 키웠어요. 계속 더 키워 볼게요", at=time.time())
    return _save(db, tries=tries, message=f"{st.get('ocpus')}코어로 돌아가는 중 · 더 키울 자리는 " + _capacity_msg(last).replace("아직 ", ""),
                 at=time.time())


def try_once(db) -> dict:
    """한 번 시도: 아직 없으면 큰 크기부터 작은 크기 순서로 만들어 보고, 작은 걸 만들었으면 다음부터는 키워 본다"""
    import oci

    st = status(db)
    if st.get("done"):
        return st
    config, compute, network, identity = _clients(db)
    if st.get("instance"):
        return _grow(db, st, compute)
    tenancy = config["tenancy"]
    # 위치 · 서브넷 · 이미지는 한 번 알아내면 기억한다 (2분마다 매번 물어 오라클이 '너무 잦다'고 막지 않게)
    ids = st.get("ids") or {}
    if not all(ids.get(k) for k in ("ad", "subnet", "image")):
        ad = identity.list_availability_domains(tenancy).data[0].name
        subnet = next(iter(network.list_subnets(tenancy).data), None)
        if subnet is None:
            return _save(db, message="서브넷을 찾지 못했어요 (오라클 콘솔에서 VCN을 먼저 만들어야 해요)", at=time.time())
        images = compute.list_images(tenancy, operating_system="Canonical Ubuntu", operating_system_version="24.04",
                                     shape=SHAPE, sort_by="TIMECREATED", sort_order="DESC").data
        if not images:
            return _save(db, message="우분투 24.04 이미지를 찾지 못했어요", at=time.time())
        ids = {"ad": ad, "subnet": subnet.id, "image": images[0].id}
        st = _save(db, ids=ids)
    tries = st.get("tries", 0) + 1
    last = None
    for ocpus, mem in SIZES:
        details = oci.core.models.LaunchInstanceDetails(
            compartment_id=tenancy, availability_domain=ids["ad"], display_name=NAME, shape=SHAPE,
            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=ocpus, memory_in_gbs=mem),
            source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=ids["image"]),
            create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=ids["subnet"], assign_public_ip=True),
            metadata={"user_data": base64.b64encode((db.get_setting("a1_init") or "").encode()).decode()})
        try:
            inst = compute.launch_instance(details).data
        except oci.exceptions.ServiceError as exc:
            last = exc
            if "capacity" not in (exc.message or "").lower() and exc.code != "InternalError":
                break      # 자리 문제가 아니면 (키·한도 등) 더 작은 크기로 해도 같으니 그만
            continue
        log.warning("큰 서버를 %s코어로 만들었어요: %s", ocpus, inst.id)
        if ocpus >= OCPUS:
            return _finish(db, tries=tries, instance=inst.id, ocpus=ocpus, created_at=time.time(),
                           message="큰 서버를 만들었어요! 15분쯤 뒤 설치가 끝나요.", at=time.time())
        return _save(db, tries=tries, instance=inst.id, ocpus=ocpus, created_at=time.time(),
                     message=f"{ocpus}코어·{mem}GB로 먼저 만들었어요! 15분쯤 뒤 설치가 끝나요. 자리가 나면 더 키워요.", at=time.time())
    if last is not None and last.code == "TooManyRequests":
        # 오라클이 '너무 잦다': 10분 쉬었다 (due 가 rest_until 을 본다)
        return _save(db, tries=tries, message=_capacity_msg(last) + " · 10분 뒤 다시", at=time.time(), rest_until=time.time() + 600)
    if last is not None and last.code in ("NotAuthorizedOrNotFound", "InvalidParameter"):
        # 기억해 둔 서브넷·이미지가 바뀌었을 수 있다 → 다음엔 다시 알아낸다
        _save(db, ids=None)
    return _save(db, tries=tries, message=_capacity_msg(last), at=time.time())


def due(db, every: float = 120) -> bool:
    st = status(db)
    return (bool(st.get("enabled")) and not st.get("done") and configured(db) and time.time() - st.get("at", 0) >= every
            and time.time() >= st.get("rest_until", 0))
