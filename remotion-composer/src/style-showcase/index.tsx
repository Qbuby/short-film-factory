import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {EditorialShowcase} from './Editorial';
import {GeometryShowcase} from './Geometry';
import {LuminousShowcase} from './Luminous';
import {WallstreetShowcase} from './Wallstreet';

const groups = [
  {component: EditorialShowcase, ids: ['mg-paperclip', 'mg-collage', 'mg-line-art', 'mg-cel-boil', 'mg-hanazi']},
  {component: GeometryShowcase, ids: ['mg-flat-vector', 'mg-isometric', 'mg-3d-render', 'mg-morph', 'mg-bauhaus']},
  {component: LuminousShowcase, ids: ['mg-hud', 'mg-liquid', 'mg-synthwave', 'mg-aurora-glass', 'mg-pixel']},
  {component: WallstreetShowcase, ids: ['mg-wallstreet']},
];

const ShowcaseRoot: React.FC = () => <>
  {groups.flatMap(({component, ids}) => ids.map(styleId => (
    <Composition key={styleId} id={`showcase-${styleId}`} component={component}
      durationInFrames={150} fps={30} width={1080} height={1920}
      defaultProps={{styleId}} />
  )))}
</>;

registerRoot(ShowcaseRoot);
