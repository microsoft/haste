// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Bridges the v8 string-based `iconName` pattern to v9 icon components
// during the FluentUI v8 -> v9 migration. Use <FluentIcon name="Add" />
// or getIcon("Add") wherever the old code passed an iconName string.
import PropTypes from "prop-types";

import {
  AddRegular,
  AppsRegular,
  AppsListRegular,
  ArrowDownloadRegular,
  ArrowForwardRegular,
  ArrowLeftRegular,
  ArrowRedoRegular,
  ArrowRightRegular,
  ArrowSortDownRegular,
  ArrowSortUpRegular,
  ArrowUndoRegular,
  ArrowUploadRegular,
  CalendarLtrRegular,
  CheckmarkRegular,
  ChevronDoubleLeftRegular,
  ChevronDownRegular,
  ChevronLeftRegular,
  ChevronRightRegular,
  ChevronUpRegular,
  CircleHalfFillRegular,
  ColumnTripleRegular,
  CopyRegular,
  CropRegular,
  CubeRegular,
  CursorRegular,
  CutRegular,
  DataTrendingRegular,
  DatabaseRegular,
  DeleteRegular,
  DismissRegular,
  DocumentRegular,
  DocumentTextRegular,
  EditRegular,
  FilterRegular,
  FolderRegular,
  FolderAddRegular,
  FolderOpenRegular,
  GlobeRegular,
  GridRegular,
  HandRightRegular,
  HomeRegular,
  ImageRegular,
  InfoRegular,
  ListRegular,
  LocationRegular,
  MailRegular,
  MapRegular,
  MoreHorizontalRegular,
  NavigationRegular,
  OptionsRegular,
  PeopleTeamRegular,
  PersonRegular,
  QuestionCircleRegular,
  RocketRegular,
  SaveRegular,
  SettingsRegular,
  ShapesRegular,
  WeatherMoonRegular,
  WeatherSunnyRegular,
} from "@fluentui/react-icons";

// Map of v8 iconName strings (as used across the app) to v9 components.
// Keys are matched case-insensitively via getIcon().
const ICONS = {
  add: AddRegular,
  arrowleft: ArrowLeftRegular,
  arrowright: ArrowRightRegular,
  fabricnewfolder: FolderAddRegular,
  analyticsreport: DataTrendingRegular,
  bulletedlist: ListRegular,
  calendar: CalendarLtrRegular,
  cancel: DismissRegular,
  checkmark: CheckmarkRegular,
  chevrondoubleleft: ChevronDoubleLeftRegular,
  chevrondown: ChevronDownRegular,
  chevronleft: ChevronLeftRegular,
  chevronleftsmall: ChevronLeftRegular,
  chevronright: ChevronRightRegular,
  chevronrightsmall: ChevronRightRegular,
  chevronup: ChevronUpRegular,
  clearnight: WeatherMoonRegular,
  columnoptions: ColumnTripleRegular,
  copy: CopyRegular,
  crop: CropRegular,
  cut: CutRegular,
  database: DatabaseRegular,
  delete: DeleteRegular,
  download: ArrowDownloadRegular,
  edit: EditRegular,
  fileimage: ImageRegular,
  filter: FilterRegular,
  folderhorizontal: FolderRegular,
  forward: ArrowForwardRegular,
  globalnavbutton: NavigationRegular,
  globe: GlobeRegular,
  gridviewsmall: GridRegular,
  grouplist: PeopleTeamRegular,
  handsfree: HandRightRegular,
  help: QuestionCircleRegular,
  home: HomeRegular,
  info: InfoRegular,
  mailforward: MailRegular,
  mapregular: MapRegular,
  mappin: LocationRegular,
  modelingview: CubeRegular,
  more: MoreHorizontalRegular,
  openfolderhorizontal: FolderOpenRegular,
  productcatalog: AppsRegular,
  redo: ArrowRedoRegular,
  releasedefinition: RocketRegular,
  reportdocument: DocumentRegular,
  save: SaveRegular,
  saveandclose: SaveRegular,
  scalevolume: CircleHalfFillRegular,
  settings: SettingsRegular,
  slider: OptionsRegular,
  sortup: ArrowSortUpRegular,
  sortdown: ArrowSortDownRegular,
  sunny: WeatherSunnyRegular,
  textdocument: DocumentTextRegular,
  undo: ArrowUndoRegular,
  upload: ArrowUploadRegular,
  userevent: PersonRegular,
  webappbuildermodule: ShapesRegular,
  // extras referenced indirectly
  appslist: AppsListRegular,
  cursor: CursorRegular,
};

/** Resolve a v8 iconName string to a v9 icon component (or null). */
// eslint-disable-next-line react-refresh/only-export-components
export function getIconComponent(name) {
  if (!name) return null;
  return ICONS[String(name).toLowerCase()] || null;
}

/** Render a v9 icon from a v8-style name. Extra props pass through. */
/* eslint-disable react-hooks/static-components */
export function FluentIcon({ name, ...rest }) {
  const Cmp = getIconComponent(name);
  return Cmp ? <Cmp {...rest} /> : null;
}
/* eslint-enable react-hooks/static-components */

FluentIcon.propTypes = {
  name: PropTypes.string.isRequired,
};
