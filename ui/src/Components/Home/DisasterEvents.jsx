// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import { geoMercator, geoPath } from 'd3-geo';
import PropType from 'prop-types';

const DisasterEvents = ({dashboardData,  width, height }) => {
  DisasterEvents.propTypes = {
    dashboardData: PropType.array.isRequired,
    width: PropType.number.isRequired,
    height: PropType.number.isRequired,
  };

  const svgRef = useRef();
  height
  useEffect(() => {
 
    const projection = geoMercator().fitSize([width, height], { type: 'Sphere' });
    const pathGenerator = geoPath().projection(projection);

    const affectedCountries = dashboardData.flatMap((project) => project.affectedCountries);


    const svg = d3.select(svgRef.current).attr('width', width).attr('height', height);


    d3.json('https://raw.githubusercontent.com/holtzy/D3-graph-gallery/master/DATA/world.geojson').then((data) => {

      var filteredData = data.features.filter((d) => d.id !== 'ATA');
      filteredData = filteredData.map((d) => {
        if (affectedCountries.includes(d.id)) {
          d.properties.affected = true;
        }
        return d;
      });

      svg
        .selectAll('path')
        .data(filteredData)
        .join('path')
        .attr('d', pathGenerator)
        .attr('stroke', '#333')
        .attr('stroke-width', 0.6)
        .on('click', (event, d) => {
          alert(`${d.properties.name}`);
        })
        .attr('fill', (d) => (d.properties.affected ? '#0078D4' : 'transparent'));
    });
  }, []);

  return <svg ref={svgRef} style={{ width: '100%', height: '100%', marginBottom: '-100px' }}></svg>;
};

export default DisasterEvents;