// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

function padDatePart(value) {
  return String(value).padStart(2, "0");
}

export function formatProjectDate(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";

  return `${padDatePart(date.getMonth() + 1)}/${padDatePart(
    date.getDate()
  )}/${date.getFullYear()}`;
}

export function parseProjectDate(value) {
  const match = /^\s*(\d{2})\/(\d{2})\/(\d{4})\s*$/.exec(value);
  if (!match) return null;

  const month = Number(match[1]);
  const day = Number(match[2]);
  const year = Number(match[3]);
  if (year < 1000) return null;

  const date = new Date(year, month - 1, day);
  date.setHours(0, 0, 0, 0);

  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }

  return date;
}