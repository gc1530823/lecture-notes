// iPhone(사파리) 안내: 홈 화면에 추가하면 앱처럼 쓰고, 녹음 중엔 화면이 꺼지지 않게 해야 한다
import { useState } from "react";
import { Icon } from "./ui";

export const isIos = () =>
  /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const standalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || (navigator as unknown as { standalone?: boolean }).standalone === true;

const KEY = "ln.iosHint";

/** 홈: 아이폰 사파리에서 처음 몇 번만 보이는 '홈 화면에 추가' 안내 */
export function IosInstallHint() {
  const [hide, setHide] = useState(() => {
    try { return localStorage.getItem(KEY) === "off"; } catch { return false; }
  });
  if (hide || !isIos() || standalone()) return null;
  const close = () => { try { localStorage.setItem(KEY, "off"); } catch { /* 저장 못 해도 지금은 닫는다 */ } setHide(true); };
  return (
    <div className="ios-hint" role="note">
      <span className="ios-hint-ic"><Icon name="house-line" size={22} /></span>
      <div className="grow">
        <b>홈 화면에 추가하면 앱처럼 써요</b>
        <p>사파리 아래 <Icon name="export" size={14} /> 공유 → <b>홈 화면에 추가</b>. 전체 화면으로 열리고 로그인도 유지돼요.</p>
      </div>
      <button className="ios-hint-x" aria-label="닫기" onClick={close}><Icon name="x" size={16} /></button>
    </div>
  );
}

/** 강의 녹음 전: 아이폰은 화면이 꺼지거나 다른 앱으로 가면 녹음이 멈춘다 */
export function IosRecordWarning() {
  if (!isIos()) return null;
  return (
    <p className="ios-rec-warn">
      <Icon name="warning-circle" size={15} /> 아이폰은 <b>화면이 꺼지거나 다른 앱으로 가면 녹음이 멈춰요.</b> 녹음하는 동안 LUNE 화면을 켜 두세요 (충전기 연결 추천).
    </p>
  );
}
