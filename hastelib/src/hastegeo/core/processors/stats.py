# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json

from hastegeo.core.config import Config
from hastegeo.core.models.stats import (
    ProjectsSummary,
    ProjectStats,
    StatsRequest,
)

from ..utils.logs import Logger
from ..utils.queues import AzureQueueHandler


class StatsPreProcessor:
    def __init__(
        self,
        request: StatsRequest,
        summary: ProjectsSummary = None,
        config: Config = None,
    ):
        if config is None:
            config = Config()
        self.queue_client = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["stats_queue_name"],
            config.queue_config["queue_account_url"],
        )
        self.request = request
        self.config = config

    def send_to_queue(self):
        self.queue_client.put_message(
            json.dumps(self.request.dict()), visibility_timeout=0
        )
        return self.request


class StatsPostProcessor:
    def __init__(
        self,
        request: StatsRequest,
        summary: ProjectsSummary = None,
        config: Config = None,
    ):
        if config is None:
            config = Config()
        self.request = request
        self.summary = ProjectsSummary() if summary is None else summary
        self.logger = Logger.get_logger(__name__)

    def update(self):
        current = {}
        for idx, project in enumerate(self.summary.projects):
            if project.projectId == self.request.projectId:
                current = project
                project_idx = idx
                break
        if not current and self.request.action == "add":
            self.summary.projects.append(
                ProjectStats(
                    projectId=self.request.projectId,
                    name=self.request.name,
                    description=self.request.description,
                    creationDate=self.request.creationDate,
                    affectedCountries=(
                        self.request.affectedCountries
                        if self.request.affectedCountries
                        else []
                    ),
                    imageLayerStats=(
                        [self.request.imageLayerStats]
                        if self.request.imageLayerStats
                        else []
                    ),
                    modelIds=self.request.modelIds,
                    imageLayerCount=(1 if self.request.imageLayerStats else 0),
                    modelsCount=len(self.request.modelIds),
                    labelsCount=(
                        self.request.imageLayerStats.labelsCount
                        if self.request.imageLayerStats
                        else 0
                    ),
                ),
            )
            return self.summary
        if not current and self.request.action == "delete":
            self.logger.info(
                f"No action taken, StatsProcessor did not find requested project {self.request.dict()}"
            )
            return self.summary
        if self.request.action == "add":
            if self.request.modelIds:
                current.modelIds += self.request.modelIds
                # Remove dupes in case the same request is somehow handled multiple times
                current.modelIds = list(set(current.modelIds))
            if self.request.imageLayerStats:
                imagelayer_found = False
                for idx, image in enumerate(current.imageLayerStats):
                    if (
                        image.imageLayerId
                        == self.request.imageLayerStats.imageLayerId
                    ):
                        current.imageLayerStats[
                            idx
                        ] = (
                            self.request.imageLayerStats
                        )  # updates labels count
                        imagelayer_found = True
                        break
                if not imagelayer_found:
                    current.imageLayerStats.append(
                        self.request.imageLayerStats
                    )
            if self.request.name:
                current.name = self.request.name
            if self.request.description:
                current.description = self.request.description
            if self.request.affectedCountries:
                current.affectedCountries = self.request.affectedCountries

        if self.request.action == "delete":
            if self.request.projectId and not (
                self.request.imageLayerStats or self.request.modelIds
            ):
                self.summary.projects.remove(current)
                self.logger.info(
                    "Deleted project stats for project id {self.request.projectId}"
                )
                return self.summary
            if self.request.imageLayerStats:
                for idx, image in enumerate(current.imageLayerStats):
                    if (
                        image.imageLayerId
                        == self.request.imageLayerStats.imageLayerId
                    ):
                        del current.imageLayerStats[idx]
                        break
            try:
                if self.request.modelIds:
                    for modelId in self.request.modelIds:
                        current.modelIds.remove(modelId)
            except ValueError:
                pass  # modelId was not there to begin with
        current.imageLayerCount = len(current.imageLayerStats)
        current.modelsCount = len(current.modelIds)
        current.labelsCount = sum(
            [image.labelsCount for image in current.imageLayerStats]
        )
        self.logger.info(
            f"Updated stats for project id {self.request.projectId}: {current.dict()}"
        )
        self.summary.projects[project_idx] = current
        return self.summary
