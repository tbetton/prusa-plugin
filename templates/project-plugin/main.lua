info = {
    id = "io.github.tbetton.starter-block.create",
    type = "project.plugin",
    title = "Starter Block",
    menu = "Examples/Starter Block",
    params = {
        { name = "width", label = "Width and depth (mm)", type = "float", default = 20 },
        { name = "height", label = "Height (mm)", type = "float", default = 1 },
    },
}

function execute(params)
    if params.width <= 0 or params.height <= 0 then
        error("Width and height must be positive.")
    end

    local mesh = api.make_cube(params.width, params.width, params.height)
    api.project:add_object({ mesh = mesh })
end
