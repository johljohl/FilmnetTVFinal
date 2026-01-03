import React from "react";

const GapOverlay = ({ seconds, nextMovie }) => {
  const formatTime = (s) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m.toString().padStart(2, "0")}:${sec
      .toString()
      .padStart(2, "0")}`;
  };

  return (
    <div className="next-overlay">
      {/* VÄNSTER SIDA: Text-gruppen */}
      <div className="overlay-text-group">
        {/* 1. Titel (Nu högst upp) */}
        <div className="next-title-display">
          {nextMovie?.tmdb_title || "Laddar schema..."}
        </div>

        {/* 2. Skådespelare */}
        {nextMovie?.actors && (
          <div className="next-actors-display">Med: {nextMovie.actors}</div>
        )}

        {/* 3. Header (Flyttad ner) */}
        <div className="overlay-header">Nästa film börjar om:</div>

        {/* 4. Klocka (Flyttad ner) */}
        <div className="countdown-time">{formatTime(seconds)}</div>
      </div>

      {/* HÖGER SIDA: Bilden */}
      {nextMovie?.poster && (
        <img
          src={nextMovie.poster}
          alt="Next Poster"
          className="next-poster-preview"
        />
      )}

      <div className="buffering-hint">Buffrar nästa sändning...</div>
    </div>
  );
};

export default GapOverlay;
