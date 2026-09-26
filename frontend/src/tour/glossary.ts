/** Short, technically accurate definitions shown the first time a term appears in a tour step. */
export const GLOSSARY: Record<string, { term: string; definition: string }> = {
  firms: { term: "FIRMS", definition: "NASA's Fire Information for Resource Management System: satellite detections of thermal anomalies from MODIS and VIIRS, delivered within hours." },
  frp: { term: "FRP", definition: "Fire Radiative Power, in megawatts: an estimate of the radiant energy a thermal source emits, derived from the satellite measurement." },
  event: { term: "Event", definition: "A cluster of satellite detections close in space (about 1.5 km) and time (gaps of up to 5 days), treated as one episode of thermal activity." },
  persistence: { term: "Persistence", definition: "Repeated thermal observations at the same place over time, classed as transient, recurring or persistent." },
  priority: { term: "Triage priority", definition: "A 0-100 score that orders the review queue from observed evidence. It is not a risk, danger or probability score." },
  ndvi: { term: "NDVI", definition: "Normalised Difference Vegetation Index: (near-infrared - red) / (near-infrared + red). Higher values indicate denser green vegetation." },
  nbr: { term: "NBR", definition: "Normalised Burn Ratio: (near-infrared - shortwave infrared) / (near-infrared + shortwave infrared). A drop after an event is associated with burned vegetation." },
  shap: { term: "SHAP", definition: "SHapley Additive exPlanations: a method that attributes a model's output to its input features, showing how each feature pushed the prediction up or down." },
  postgis: { term: "PostGIS", definition: "The geospatial extension of PostgreSQL, used here for distance, nearest-neighbour and area queries." },
  holdout: { term: "Spatial hold-out", definition: "Keeping whole geographic areas out of training so evaluation reflects performance on places the model has not seen, instead of nearby near-duplicates." },
  worldcover: { term: "ESA WorldCover", definition: "A 10 m global land-cover map from the European Space Agency (2021 edition), classifying cropland, tree cover, built-up area and more." },
  distanceDecay: { term: "Distance-decay attribution", definition: "Support for a facility link that falls off with distance: a facility 300 m away counts for much more than one 8 km away, and nothing is 'inside' by default." },
  rules: { term: "Rule cascade", definition: "An ordered set of transparent rules from published remote-sensing knowledge (e.g. oil/gas site + night-time persistence suggests a flare). Every decision records which rules fired." },
};
