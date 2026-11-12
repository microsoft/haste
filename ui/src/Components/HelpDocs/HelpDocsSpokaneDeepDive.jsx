// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useState } from "react";
import { Link } from "@fluentui/react-components";
import {
  spokaneDeepDiveEpisodes as episodes,
  spokaneDeepDiveMediaBase as mediaBase,
} from "./spokaneDeepDiveEpisodes";

const HelpDocsSpokaneDeepDive = () => {
  const [failedEpisodes, setFailedEpisodes] = useState([]);
  const handleVideoError = (episodeId) => {
    setFailedEpisodes((previous) =>
      previous.includes(episodeId) ? previous : [...previous, episodeId]
    );
  };

  return (
    <section
      id="spokane-deep-dive"
      aria-labelledby="spokane-deep-dive-title"
      className="pt-4"
    >
      <h2 id="spokane-deep-dive-title">Spokane Deep Dive</h2>
      <p>
        Follow this six-part demonstration of HASTE using the Spokane example,
        from labeling and building embeddings to editing predictions and
        understanding outputs, with a bonus episode on the Open Data Catalog.
      </p>
      <p>
        Allow about 17 minutes for the full series. Watch in order or choose the
        episode you need below. English captions are available through each
        player&apos;s caption controls.
      </p>
      {episodes.map((episode) => (
        <section
          key={episode.id}
          id={`spokane-${episode.id}`}
          aria-labelledby={`spokane-${episode.id}-title`}
          className="pt-4 pb-4"
        >
          <h3 id={`spokane-${episode.id}-title`}>{episode.title}</h3>
          <p>{episode.description} ({episode.duration})</p>
          <video
            controls
            preload="none"
            playsInline
            crossOrigin="anonymous"
            poster={`${mediaBase}/${episode.file}.jpg`}
            aria-label={`Spokane deep dive: ${episode.title}`}
            className="w-100 mb-3 help-docs-video-wrapper"
            onError={() => handleVideoError(episode.id)}
          >
            <source
              src={`${mediaBase}/${episode.file}.mp4`}
              type="video/mp4"
              onError={() => handleVideoError(episode.id)}
            />
            <track
              kind="captions"
              src={`${mediaBase}/${episode.file}.vtt`}
              srcLang="en"
              label="English"
            />
            Your browser does not support embedded video. Use the link below
            to open this episode.
          </video>
          {failedEpisodes.includes(episode.id) && (
            <p role="alert">
              {episode.title} video could not be loaded. Try opening it in a new tab using
              the link below.
            </p>
          )}
          <p>
            <Link
              inline
              href={`${mediaBase}/${episode.file}.mp4`}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open {episode.title} video in a new tab
            </Link>
          </p>
        </section>
      ))}
    </section>
  );
};

export default HelpDocsSpokaneDeepDive;
