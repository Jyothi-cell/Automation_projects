import streamlit as st
import re

# Title of the app
st.title('Table Conversion')

# Text area for user input
user_input = st.text_area("Enter your text data here", height=200)

def parse_text_to_table_tags(text):
    # Split the content into rows based on newline
    rows = [row for row in text.strip().split('\n') if row.strip()]

    # Determine the maximum number of columns in any row
    max_columns = 0
    parsed_rows = []

    for row in rows:
        # Split based on whitespace or other delimiters
        columns = re.split(r'\s{2,}|\t', row.strip())
        max_columns = max(max_columns, len(columns))
        parsed_rows.append(columns)

    # Generate XML structure
    xml_content = f'<tbl ID="tbl1" maxsize="default">\n'
    xml_content += '<table colsep="0" rowsep="0">\n'
    xml_content += f'<?ctbl ampex.cols="{max_columns}"?>\n'
    xml_content += f'<tgroup cols="{max_columns}">\n'
    xml_content += '<?ctbl ampex.table.align="center"?>\n'
    xml_content += '<?ctbl ampex.colwidth="100"?>\n'
    
    # Add colspecs for each column
    for i in range(max_columns):
        xml_content += f'<colspec align="left" colname="col{i+1}" colnum="{i+1}"/>\n'
        xml_content += '<?ctbl ampex.vert.just="top"?>\n'
        xml_content += '<?ctbl ampex.colwidth="100"?>\n'

    xml_content += '<tbody>\n'
    
    for row in parsed_rows:
        xml_content += "<row>\n"
        for i in range(max_columns):
            column_content = row[i].strip() if i < len(row) else ""
            xml_content += f'<entry colname="col{i+1}" align="left" valign="top"><para><paratext ID="p">{column_content}</paratext></para></entry>\n'
        xml_content += "</row>\n"
    
    xml_content += "</tbody>\n</tgroup>\n</table>\n</tbl>"

    return xml_content

if user_input:
    # Convert the input text to XML table tags
    xml_content = parse_text_to_table_tags(user_input)
    
    # Display XML content
    st.text_area('Generated XML', xml_content, height=300)

    # Download XML file
    st.download_button(
        label="Download XML",
        data=xml_content,
        file_name='output.xml',
        mime='application/xml'
    )
