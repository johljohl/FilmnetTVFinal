import { useState, useEffect, useRef } from "react";
import Hls from "hls.js";
import "./index.css";
import GapOverlay from "./GapOverlay";

const API_URL = "http://192.168.0.3:8000"; // Kontrollera din IP

// --- VIDEO PLAYER COMPONENT ---
const VideoPlayer = ({ src }) => {
  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const lastTimeRef = useRef(0);
  const stallCountRef = useRef(0);

  useEffect(() => {
    let hls = null;
    if (hlsRef.current) hlsRef.current.destroy();

    const video = videoRef.current;
    if (!video) return;

    if (Hls.isSupported()) {
      hls = new Hls({
        debug: false,
        manifestLoadingTimeOut: 10000,
        enableWorker: true,
        maxBufferLength: 30,
        maxMaxBufferLength: 60,
      });
      hlsRef.current = hls;
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch((e) => console.log("Autoplay blocked:", e));
      });

      hls.on(Hls.Events.ERROR, (event, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              hls.startLoad();
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              hls.recoverMediaError();
              break;
            default:
              hls.destroy();
              break;
          }
        }
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      video.addEventListener("loadedmetadata", () => video.play());
    }
    return () => {
      if (hls) hls.destroy();
    };
  }, [src]);

  // Anti-freeze monitor
  useEffect(() => {
    const checkStall = setInterval(() => {
      const video = videoRef.current;
      if (video && !video.paused) {
        if (video.currentTime === lastTimeRef.current) stallCountRef.current++;
        else {
          stallCountRef.current = 0;
          lastTimeRef.current = video.currentTime;
        }

        if (stallCountRef.current > 5) {
          console.log("⚠️ Video stall detected, reloading...");
          stallCountRef.current = 0;
          if (hlsRef.current) {
            hlsRef.current.recoverMediaError();
          }
        }
      }
    }, 1000);
    return () => clearInterval(checkStall);
  }, [src]);

  return (
    <video
      ref={videoRef}
      className="video-layer"
      autoPlay
      muted
      playsInline
      controls={false}
    />
  );
};

// --- MAIN APP ---
function App() {
  const [wallClock, setWallClock] = useState("00:00:00");
  const [data, setData] = useState(null);
  const [activeTab, setActiveTab] = useState(null);
  const [localGapSeconds, setLocalGapSeconds] = useState(0);

  // 1. Klocka
  useEffect(() => {
    const timer = setInterval(
      () => setWallClock(new Date().toLocaleTimeString("sv-SE")),
      1000
    );
    return () => clearInterval(timer);
  }, []);

  // 2. Hämta data från Server
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(`${API_URL}/api/status`);
        const json = await res.json();
        setData(json);
        setActiveTab((prev) => (prev ? prev : json.active_club));

        if (json.is_gap && json.gap_time) {
          const [min, sec] = json.gap_time.split(":").map(Number);
          const totalSec = min * 60 + sec;

          if (Math.abs(totalSec - localGapSeconds) > 2) {
            setLocalGapSeconds(totalSec);
          }
        }
      } catch (err) {}
    };
    fetchStatus();
    const poller = setInterval(fetchStatus, 2000);
    return () => clearInterval(poller);
  }, []);

  // 3. Lokal nedräkning
  useEffect(() => {
    if (localGapSeconds <= 0) return;
    const countdown = setInterval(() => {
      setLocalGapSeconds((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(countdown);
  }, [localGapSeconds]);

  if (!data)
    return (
      <div
        style={{
          padding: 20,
          color: "#fff",
          background: "#000",
          height: "100vh",
        }}
      >
        Ansluter till Filmnet...
      </div>
    );

  const currentTab = activeTab || data.active_club;
  const showGapOverlay = localGapSeconds > 0;

  const displayMovie = showGapOverlay
    ? data.next_movie
    : data.playing_now || data.next_movie;

  const schedule = data.all_schedules ? data.all_schedules[currentTab] : [];

  return (
    <>
      <div className="header">
        <div
          className="header-logo"
          style={{ color: data.active_color || "#fff" }}
        >
          {data.active_club || "FILMNET"}
        </div>
        <div className="wall-clock">{wallClock}</div>
      </div>

      <div className="main-container">
        <div className="video-section">
          <div className="video-box">
            {/* VIKTIG WRAPPER FÖR ATT CSS SKA FUNKA */}
            <div className="video-wrapper">
              {/* LAGER 1: Overlay */}
              {showGapOverlay && (
                <GapOverlay
                  seconds={localGapSeconds}
                  nextMovie={data.next_movie}
                />
              )}

              {/* LAGER 2: Videospelare */}
              <VideoPlayer src={`${API_URL}/stream.m3u8`} />
            </div>
          </div>

          <div className="meta-card">
            {displayMovie?.poster && (
              <img
                className="meta-poster"
                src={displayMovie.poster}
                onError={(e) => (e.target.style.display = "none")}
                alt="poster"
              />
            )}
            <div className="meta-info">
              <h2>
                {showGapOverlay
                  ? `KOMMER SNART: ${displayMovie?.tmdb_title}`
                  : displayMovie?.tmdb_title}
              </h2>
              <p className="meta-plot">{displayMovie?.plot}</p>
            </div>
          </div>
        </div>

        <div className="epg-container">
          <div className="tabs">
            {["Morning Club", "Royal Club", "Night Club"].map((club) => (
              <button
                key={club}
                className={`tab-btn ${currentTab === club ? "active" : ""}`}
                onClick={() => setActiveTab(club)}
              >
                {club.replace(" Club", "").toUpperCase()}
              </button>
            ))}
          </div>
          <div className="epg-list">
            {schedule.map((item, idx) => {
              const isNow = currentTab === data.active_club && item.is_current;
              return (
                <div key={idx} className={`epg-row ${isNow ? "now" : ""}`}>
                  <div className="epg-time">{item.time}</div>
                  <div className="epg-title">{item.title}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
}

export default App;
