// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from "prop-types";
import { FluentIcon } from "../../util/icons";

const HelpDocsOverviewBubble = ({ iconName, title, text, link }) => {
  return (
    <div className="col d-flex flex-column p-3 help-docs-overview-bubble">
      <div className='d-flex align-items-center'>
        <FluentIcon name={iconName} className="pe-2" style={{ fontSize: '20px' }} />
        <h2 className='p-0 m-0'>{title}</h2>
      </div>
      <hr className='' />
      <p className='p-0 m-0'>{text}</p>
      <a className='mt-3' href={`./${link}`}>Read More</a>
    </div>
  );
};

HelpDocsOverviewBubble.propTypes = {
  iconName: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  text: PropTypes.string.isRequired,
  link: PropTypes.string.isRequired,
};

export default HelpDocsOverviewBubble;
