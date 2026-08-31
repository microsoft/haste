// Components
import {
  Text,
  Tooltip,
} from "@fluentui/react-components";

import PropTypes from "prop-types";

const BaseModelRow = ({item}) => {
  BaseModelRow.propTypes = {
    item: PropTypes.object.isRequired,
  };

  return (
    <tr key={item.userId}>
      <td className="">
        <Text className="pe-4">
          {item.name}
        </Text>
      </td>
      <td>
        <Text className="pe-4 ellipsis">
          <Tooltip content={item.email} relationship="label">
            <span>{item.sourceURL}</span>
          </Tooltip>
        </Text>
      </td>
      <td>
        <Text className="pe-4">
          {item.creationDate}
        </Text>
      </td>
    </tr>
  );
};

export default BaseModelRow;
