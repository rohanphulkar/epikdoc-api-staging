def calculate_class_percentage(prediction):
    """
    Calculate the percentage of each class in the predictions.

    :param prediction: The prediction object returned from Roboflow.
    :return: A dictionary with class names as keys and their corresponding percentage as values.
    """
    total_area = 0
    class_areas = {}

    # Calculate total area and class-specific areas
    for item in prediction['predictions']:
        box_width = item['width']
        box_height = item['height']
        box_area = box_width * box_height
        total_area += box_area

        # Add area to the corresponding class
        class_name = item['class']
        if class_name not in class_areas:
            class_areas[class_name] = 0
        class_areas[class_name] += box_area

    # Calculate the percentage of each class
    class_percentages = {}
    if total_area > 0:
        for class_name, area in class_areas.items():
            class_percentages[class_name] = round((area / total_area) * 100, 2)  # Round to 2 decimal places
    else:
        return {class_name: 0 for class_name in class_areas}

    return class_percentages

