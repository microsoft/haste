// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
export function convertMonthToString(month) {
    const monthNames = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December"
    ];
    return monthNames[month - 1];
}

export function convertDateToString(date) {
    const dateObj = new Date(date);
    const month = convertMonthToString(dateObj.getMonth() + 1);
    const day = dateObj.getDate();
    const year = dateObj.getFullYear();
    return `${month} ${day}, ${year}.`;
}

export function limitTextLength(text, maxLengthSm, maxLengthLg) {
    if (!text) return "";
    const isLargeScreen = typeof window !== "undefined" && window.innerWidth >= 992;
    const maxLength = isLargeScreen ? maxLengthLg : maxLengthSm;
    if (maxLength === false) return text;
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
}